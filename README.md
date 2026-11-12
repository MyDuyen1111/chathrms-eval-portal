# Chatbot Eval Portal cho ChatHRMS

Portal để tester (QC, BA) tập quy trình đánh giá chatbot theo QC handbook v13 trên ChatHRMS, chatbot HR mẫu ở repo `chathrms`: upload và khoá eval set, chạy run, review, ra các con số báo cáo. Handbook không có trong repo; các mục `§` trong code và README là mục của handbook.

Portal có hai chế độ:

- **Không đặt `CHATHRMS_URL`:** chạy trên mock. `MockChat` trả lời đúng dạng response của ChatHRMS nhưng nội dung là giả, dùng để thử portal trên máy.
- **Đặt `CHATHRMS_URL`:** gọi ChatHRMS thật (mục "Chạy với ChatHRMS thật").

Judge thật có sẵn nhưng mặc định tắt, Administrator bật ở trang Judge. Khi chatbot hoặc judge còn là mock, thanh trên cùng hiện nhãn "Mock data" và mọi con số là giả.

## Chạy thử trên máy

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/make_sample.py              # tạo hai file eval set mẫu trong samples/
.venv/bin/flask --app evalportal create-admin        # tạo tài khoản admin; mật khẩu tạm chỉ in một lần
.venv/bin/flask --app evalportal run --port 5057     # mở http://127.0.0.1:5057
```

`make_sample.py` tạo hai file:

| File | Nội dung |
|---|---|
| `ChatHRMS eval set - exam.xlsx` | 15 câu thật (14 Exam, 1 Safety). Đáp án nằm trong `samples/kb` của repo ChatHRMS. Dùng file này khi chạy với ChatHRMS thật |
| `ChatHRMS eval set - mock.xlsx` | 140 câu giả theo tỉ lệ §3.1 (120 Exam, 20 Safety), để thử Random 15, Independent 50 và report trên mock. ChatHRMS thật không trả lời được các câu này |

Luồng thử nhanh:

1. Đăng nhập `admin`, đổi mật khẩu, thêm `qc.lead` (QC) và `ba.lead` (BA) ở Users rồi lưu lại hai mật khẩu tạm.
2. Đăng nhập `qc.lead`, đổi mật khẩu, upload `samples/ChatHRMS eval set - mock.xlsx` ở Eval sets.
3. Đăng nhập `ba.lead` ở cửa sổ ẩn danh, đổi mật khẩu, bấm Lock rồi xác nhận để có `gs1`.
4. Quay lại `qc.lead`: Runs, New run, chọn Baseline, tick Quick checks, Start run.

Biến môi trường của mock:

| Biến | Tác dụng |
|---|---|
| `MOCK_BUILD` | Build mà mock báo đang chạy (mặc định `b118`) |
| `MOCK_FAIL_CASE=MOCK-072` | Mock trả 429 đúng ở câu này, để xem màn hình run bị dừng |
| `MOCK_CONFIRM=1` | Mock tóm ý và hỏi xác nhận ở lượt đầu như handbook §3.2. Mặc định tắt vì ChatHRMS không có bước này: mock trả lời luôn, luật Intent confirmation Fail ở mọi câu phải tra tài liệu |
| `PORTAL_HTTPS=1` | Bật cờ Secure cho cookie. Bắt buộc khi chạy thật sau HTTPS |

Chạy test: `.venv/bin/python -m unittest discover -s tests -t .`

## Chạy với ChatHRMS thật

| Biến | Tác dụng |
|---|---|
| `CHATHRMS_URL` | Địa chỉ backend ChatHRMS, ví dụ `http://backend:8000` |
| `CHATHRMS_PASSWORD`, `CHATHRMS_ADMIN_PASSWORD` | Mật khẩu nhân viên và admin đặt lúc seed ChatHRMS; client thử lần lượt cả hai |
| `CHATHRMS_BUILD` | Build ghi vào run, mặc định `live` (ChatHRMS chưa có API build) |

1. Admin ChatHRMS upload các file trong `samples/kb` của repo ChatHRMS ở tab Knowledge Base.
2. Upload `samples/ChatHRMS eval set - exam.xlsx` ở Eval sets, BA khoá, rồi chạy run như luồng ở trên.
3. `MockJudge` không chấm được bot thật: Administrator phải bật judge thật ở trang Judge, trước đó nhãn "Mock data" vẫn hiện.

```bash
docker build -t eval-portal .
docker run -d -p 15500:15500 -v portal-data:/app/instance -e CHATHRMS_URL=... -e CHATHRMS_PASSWORD=... -e CHATHRMS_ADMIN_PASSWORD=... eval-portal
docker exec -it <container> flask --app evalportal create-admin   # mật khẩu tạm chỉ in một lần
```

Image bật cookie Secure (`PORTAL_HTTPS=1`), nên phải mở qua HTTPS.

### Portal đọc response của ChatHRMS thế nào

- **Cột `user`:** file eval set có cột `user`, là mã nhân viên đăng nhập để hỏi (ví dụ `NV001`, `HR01`). Mỗi câu đăng nhập lại và mở một hội thoại mới.
- **Kết quả câu trả lời:** ChatHRMS không có mã outcome, portal đọc từ `trace`. Có `trace.context` (bot đã tìm tài liệu) thì là câu trả lời từ tài liệu, và Groundedness chấm trên đoạn tài liệu đó.
- **Khi ChatHRMS lỗi:**
  - ChatHRMS không với tới LLM (`fallback:offline_policy_search`) thì dừng cả run.
  - Một lần gọi LLM lỗi hoặc quá 25 giây (`fallback:ai_unavailable`) thì tính như chat timeout: thử lại một lần, rồi Fail riêng câu đó (System error).
- **Citation:** lấy từ thẻ `[Nguồn: ...]` trong câu trả lời. Thẻ này không có section hay trang, nên luật Citation format luôn Fail.
- **Lượt xác nhận:** chỉ có bản nháp ticket (`rule:ticket_workflow`), runner trả lời "Yes" như với bước xác nhận ý định.

## Bật judge thật

1. Administrator lưu endpoint, key, model ở trang Judge và bấm Test connection.
2. Chạy `.venv/bin/flask --app evalportal check-judge` trên server, lúc không có run nào đang chạy.
   - Lệnh này mở DB như lúc portal khởi động, nên run đang dở sẽ hiện Failed.
   - Lệnh chấm khoảng 30 ví dụ lấy từ handbook, không gửi câu nào trong eval set, và báo `WRONG` ở ví dụ model chấm sai.
   - Có `WRONG` thì sửa prompt hoặc đổi model, chưa bật.
3. Tick Use for runs rồi Save. Từ run sau, câu hỏi, câu trả lời và đoạn tài liệu đi qua router. Form New run cho QC thấy nơi nhận trước khi bấm chạy.
4. Prompt trong `evalportal/judge.py` là bản đầu, chưa được chỉnh theo kết quả thật. Trước khi tin con số, QC phải chấm Independent 50 và xem disagreement rate (§5.4).

Mỗi câu tốn tối đa 6 lệnh gọi model. Router có prompt style hay fallback thì nên tắt: chúng đổi lời hoặc đổi model mà version judge không biết. Run nào có hơn một model trả lời thì trang run cảnh báo.

## Runner cho AI team

Chạy Practice và Quick checks ngoài portal. Runner không mở database của portal, và từ chối file có dòng Exam:

```bash
JUDGE_ENDPOINT=... JUDGE_API_KEY=... JUDGE_MODEL=... \
  .venv/bin/python scripts/practice_run.py "ChatHRMS eval set - practice.xlsx" --set "Quick checks" --out results.csv
```

Exit code:
- `0`: mọi Quick check đạt.
- `1`: có Quick check Fail.
- `2`: không chạy được.

Câu Quick checks bị judge chấm Fail được chạy lại một lần. Runner hiện chỉ gọi `MockChat`, nên exit 0 chưa nói gì về ChatHRMS.

## Cấu trúc

| File | Nội dung |
|---|---|
| `evalportal/evalset.py` | Đọc và kiểm tra file Excel |
| `evalportal/scoring.py` | Công thức các con số, không có I/O |
| `evalportal/chatapi.py` | Đọc response của ChatHRMS (trace, thẻ `[Nguồn: ...]`) |
| `evalportal/chathrms.py` | Chat client cho ChatHRMS: đăng nhập theo cột `user`, gọi `/api/chat` |
| `evalportal/runner.py` | Chạy một run: gọi chatbot, chấm, lưu kết quả |
| `evalportal/web/` (một module mỗi khu: `account`, `admin`, `evalsets`, `runs`, `review`...), `templates/` | Các màn hình và phân quyền |
| `evalportal/db.py` | Schema và kết nối database |
| `evalportal/judge.py` | Judge thật: prompt và cách đọc kết quả |
| `evalportal/judgeconfig.py` | Kiểm tra cấu hình judge, gọi router |
| `evalportal/judgecheck.py` | Các ví dụ handbook cho lệnh `check-judge` |
| `evalportal/mocks.py` | `MockChat` (trả lời theo dạng ChatHRMS), `MockJudge` |
| `scripts/make_sample.py` | Tạo hai file eval set mẫu |
| `scripts/practice_run.py` | Runner của AI team |

**Database:** SQLite trong `instance/`. Đổi sang database khác thì thay `connect()` và các câu SQL trong `db.py`, `web/`, `runner.py`.

**Hosting:** `flask run` chỉ để thử trên máy. Run chạy bằng thread trong tiến trình web, nên chỉ được chạy một worker; khởi động lại giữa chừng thì run đó chuyển sang Failed. `Dockerfile` chạy gunicorn đúng một worker.

## Bí mật của bộ Exam

- `instance/` (chứa database) và `samples/`, `*.xlsx` nằm trong `.gitignore`. Không commit file Exam.
- Copy error details và các lỗi lưu trong run không chứa câu hỏi hay câu trả lời.

## Khác với handbook

- **Công nghệ:** portal viết bằng Python, Flask và SQLite thay vì .NET và `Microsoft.Extensions.AI.Evaluation`. Vì vậy tab Report là HTML tự dựng, không phải report của thư viện (§8.2).
- **Role Administrator** thay cho Account admin (§4.2).
  - Theo §4.2, AI team không được giữ tài khoản `admin`: tài khoản này tạo được user QC, mà user QC đọc được câu Exam.
  - Người giữ `admin` còn đổi được nơi nhận câu Exam. Vì vậy form New run và từng run hiện nơi nhận cho QC thấy; lịch sử đầy đủ chỉ Administrator xem, ở trang Judge.
- **Cột `topic_group`** của §1.5 đổi tên thành `category`, cả trong file eval set lẫn trên portal. File cũ có cột `topic_group` vẫn upload được.
- **Judge** đi qua router tương thích OpenAI (9router) thay vì deployment Azure như §8. Router gửi câu hỏi tới provider nó được cấu hình và có thể fallback sang provider khác.

## Các mặc định của portal

Các điểm dưới đây handbook chưa chốt, hoặc portal làm thêm so với handbook; portal đang làm theo cách trong bảng.

| # | Điểm | Portal đang làm |
|---|---|---|
| 1 | So sánh hai run khác version | So trên câu trùng id và trùng nội dung (hash), bỏ qua câu đã đổi |
| 2 | Lỗi khi gọi chatbot | 429, 5xx, ChatHRMS không gọi được LLM dừng cả run. Timeout thử lại 1 lần rồi Fail câu đó |
| 3 | Baseline | Independent 50 thay Random 15. Trước khi chấm xong 50 câu: ẩn Judge theo từng câu chưa Save, các chip khác, tab Report và bảng theo category. Tỉ lệ tính theo kết luận QC lưu lần đầu |
| 4 | Dry run | Chỉ chạy trên version đã khoá, theo §4.3 |
| 5 | Build | ChatHRMS chưa có API build, nên run ghi `CHATHRMS_BUILD` |
| 6 | Trang Users | Chỉ Administrator vào được, và role này chỉ thấy Users, không mở được Eval sets hay Runs. Hai lead là tài khoản QC và BA thường, Administrator đặt lại mật khẩu và khoá được. Dòng Administrator không có nút; quên mật khẩu `admin` chỉ xử lý được trong DB |
| 7 | Add-on | Chạy riêng trên cùng build, cùng quy tắc review |
| 8 | Safety | Cột tuỳ chọn `leak_strings`, §1.5 không có cột này. Câu Safety thiếu cột thì trang Eval sets cảnh báo và chỉ judge chấm. Tài liệu bẫy do QC thử bằng tay |
| 9 | Đếm số | Tử số Made-up nằm trong mẫu số. Required rules không trừ câu excluded. Câu lỗi hệ thống không có rule |
| 10 | File và lịch sử | `;` ngăn cách nhiều tài liệu. Fail list là xlsx. Review sửa lại được, mọi lần lưu đều giữ lại |
| 11 | Tên run | Trùng tên thì thêm `-r2`, `-r3`, kể cả với run Official sau một run bị dừng |
| 12 | Preview | Thêm ngoài handbook: nút View ở bảng Versions mở bảng case; BA Lock được ngay trên trang đó |
| 13 | Cấu hình judge | Thêm ngoài handbook: trang Judge của Administrator lưu endpoint, API key, model, reasoning effort của router tương thích OpenAI và thử kết nối được. Run dùng `MockJudge` cho tới khi tick Use for runs. Endpoint phải là https, riêng http chỉ dành cho router trên cùng máy hoặc địa chỉ IP nội bộ. Key nằm ở `instance/judge_api_key`, không vào DB; đổi endpoint phải nhập lại key. Router redirect thì coi là lỗi, để key không đi nơi khác |
| 14 | So sánh run | Version judge gồm mã băm của prompt, tên model và effort. Đổi một trong ba thì run không so với run trước (§6.1 chỉ nói prompt) |
| 15 | Judge lỗi | 429, 5xx, mất kết nối, kết quả sai định dạng: thử lại sau 5 và 20 giây rồi dừng cả run, không lưu kết quả. Từ chối (400, 401, 403, 404) dừng ngay. Câu trả lời từ tài liệu mà không có đoạn tài liệu cũng dừng run, vì Fail ở Groundedness sẽ tính vào con số Made-up |
| 16 | Cost và telemetry | §8.1 chỉ ghi tên, chưa nói đo gì. Trang run hiện số lượt chatbot, số lệnh judge, token vào và ra, model đã trả lời, nơi nhận. Chưa quy ra tiền vì router không báo giá |
| 17 | Quick checks | 100% tính theo §3.6: mọi câu Pass, luật bắt buộc không làm Fail mà báo riêng. File Practice không bắt buộc `approved_by` |

## Giới hạn của ChatHRMS so với handbook

- **Build:** chưa có API, run ghi `CHATHRMS_BUILD`.
- **Xác nhận ý định (§3.2):** ChatHRMS không tóm ý và hỏi lại, nên luật Intent confirmation Fail ở mọi câu phải tra tài liệu, trừ khi bot tạo bản nháp ticket.
- **Citation:** chỉ có tên tài liệu, không có section hay trang, nên luật Citation format luôn Fail.
- **Bộ lọc nội dung:** ChatHRMS không có, nên metric "Blocked by chatbot" của bộ Safety không bao giờ xuất hiện; câu tấn công được judge chấm theo câu trả lời.
