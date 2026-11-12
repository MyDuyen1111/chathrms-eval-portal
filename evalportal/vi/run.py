"""The run page (run.html and its _run_*.html tabs): Summary, Report, Review and the review form.

Follows the Vietnamese QC handbook: a case is "câu", grading is "chấm", reviewing stays "review",
and AI team, Note and the handbook's metric, chip and field names stay English.
"""
VI = {
    # Header, running and failed runs
    "team target {target}": "mục tiêu nhóm {target}",
    "The router answered with more than one model in this run ({models}), so these verdicts did not all come from one judge. Check the router's fallback settings before trusting them.":
        "Trong run này router đã trả lời bằng hơn một model ({models}), nên các kết luận không đến từ cùng một judge. Kiểm tra cài đặt fallback của router trước khi tin các kết luận này.",
    "Progress of the current step": "Tiến độ của bước hiện tại",
    "Started": "Bắt đầu lúc",
    "by {name}. You can leave this page; the run keeps going.": "do {name} chạy. Có thể rời trang này, run vẫn tiếp tục chạy.",
    "Results appear when the run completes.": "Kết quả hiện ra khi run chạy xong.",
    "Copies run id, failed step, error message and case number, with no question or answer text. Send it to the AI team. Do not start a rerun yourself.":
        "Sao chép run id, bước bị lỗi, thông báo lỗi và số thứ tự câu, không kèm nội dung câu hỏi hay câu trả lời. Gửi cho AI team. Không tự chạy lại.",

    # Summary
    "Judge pass rate (before review)": "Judge pass rate (trước review)",
    "not reviewed, not reported": "không review, không báo cáo",
    "Sensitive data leaks (after review)": "Sensitive data leaks (sau review)",
    "must be 0": "phải bằng 0",
    "after review": "sau review",
    "Answer acceptance rate (after review)": "Answer acceptance rate (sau review)",
    "{n} excluded": "{n} câu không tính",
    "Review {done} / {total}": "Đã review {done} / {total}",
    "see breakdown": "xem chi tiết",
    "{n} rule target": "{n} mục tiêu luật",
    "{n} rule targets": "{n} mục tiêu luật",
    "Team targets, not client commitments. Levels with Foundation are agreed after baseline; do not send these to the client before that.":
        "Đây là mục tiêu nội bộ của nhóm, không phải cam kết với khách. Mức với Foundation chỉ chốt sau baseline; trước đó không gửi các mục tiêu này cho khách.",
    "Review complete: {done} / {total}.": "Đã review xong: {done} / {total}.",
    "False pass (independent)": "False pass (Independent 50)",
    "Disagreement rate (random 15)": "Disagreement rate (Random 15)",
    "Excluded: {document} Document, {eval_set} Eval set.": "Không tính: {document} Document, {eval_set} Eval set.",
    "These are the judge's numbers. Review {done} / {total} done; do not report them to the client.":
        "Đây là số của judge. Đã review {done} / {total}; không báo các số này cho khách.",
    "Go to review": "Sang tab Review",
    "The disagreement rate is above 8%. Stop and tell the AI team: this run's numbers cannot be used yet.":
        "Disagreement rate vượt 8%. Dừng lại và báo AI team: chưa dùng được số của run này.",
    "Required rules breakdown": "Chi tiết Required rules",
    "Rule": "Luật",
    "Passed / applied": "Pass / áp dụng",
    "Rate": "Tỷ lệ",
    "Target": "Mục tiêu",
    "Cases": "Số câu",
    "vs previous official, after review": "So với Official trước, sau review",
    "Acceptance after review": "Acceptance sau review",
    "For the AI team": "Gửi AI team",
    "Copy": "Sao chép",
    "Counts only. Never send question or answer text to the AI team.":
        "Chỉ gửi số đếm. Không bao giờ gửi nội dung câu hỏi hay câu trả lời cho AI team.",

    # Report
    "The report shows the judge's verdicts, so it stays closed until Independent 50 is finished.":
        "Report hiện kết luận của judge, nên tab này đóng cho tới khi chấm xong Independent 50.",
    "These are the judge's verdicts before review, so they do not change with QC's decisions.":
        "Đây là kết luận của judge trước review, nên không đổi theo kết luận của QC.",
    "AI Evaluation Report": "Báo cáo đánh giá AI",
    "All Evaluations": "Tất cả câu",
    "Overall result": "Kết quả chung",
    "Rule: {name}": "Luật: {name}",
    "Reason: {reason}": "Lý do: {reason}",
    "Back to review": "Quay lại Review",
    "Conversation": "Hội thoại",
    "Generated at {time} by Chatbot Eval Portal · judge prompt {prompt}":
        "Tạo lúc {time} bởi Chatbot Eval Portal · judge prompt {prompt}",

    # Review
    "A dry run is not reviewed and is never reported.": "Dry run không được review và không bao giờ được báo cáo.",
    "Baseline: grade Independent 50 first. The judge's verdict on a case appears after you save it, and the other chips open when all of them are saved.":
        "Baseline: chấm Independent 50 trước. Kết luận của judge cho một câu chỉ hiện sau khi bấm Save, và các chip khác mở khi đã lưu đủ 50 câu.",
    "Saved": "Đã lưu",
    "You said {qc}; the judge said {judge}.": "Đã chọn {qc}; judge chọn {judge}.",
    "Next list: {list}.": "Danh sách tiếp theo: {list}.",
    "See the numbers on Summary": "Xem số ở tab Summary",
    "{n} left": "còn {n}",
    "done": "xong",
    "Reviewed": "Đã review",
    "{list} cases": "Các câu trong {list}",
    "Hidden": "Ẩn",
    "Not reviewed": "Chưa review",
    "No cases in this list.": "Danh sách này không có câu nào.",
    "Close {case}": "Đóng {case}",
    "Close": "Đóng",
    "Question": "Câu hỏi",
    "Chatbot answer": "Câu trả lời của chatbot",
    "No answer was received.": "Không nhận được câu trả lời.",
    "p. {pages}": "tr. {pages}",
    "nothing": "không có",
    "Full conversation, {n} messages": "Toàn bộ hội thoại, {n} tin nhắn",
    "Eval set expects": "Eval set yêu cầu",
    "Key facts in the eval set": "Key facts trong eval set",
    "✓ the judge found it in the answer": "✓ judge thấy có trong câu trả lời",
    "What the chatbot retrieved from the documents": "Chatbot lấy được gì từ tài liệu",
    "Not kept for this run: runs started before this view existed did not save it.": "Run này không lưu phần này: các run chạy trước khi có mục này chưa lưu lại.",
    "The chatbot retrieved nothing.": "Chatbot không lấy được đoạn tài liệu nào.",
    "Eval set source": "Nguồn trong eval set",
    "Chatbot cited": "Chatbot trích",
    "Stated": "Có nêu",
    "stated:": "có nêu:",
    "Missing": "Thiếu",
    "missing:": "thiếu:",
    "What to check": "Cần kiểm tra",
    "Hidden until you save: grade it yourself first.": "Ẩn cho tới khi bấm Save: tự chấm trước.",
    "The case passes only when every check passes. Required rules are counted on Summary and never fail a case.":
        "Câu chỉ Pass khi mọi mục đều Pass. Required rules được tính ở tab Summary và không bao giờ làm câu bị Fail.",
    "Last saved by {name} on {date}": "{name} lưu lần cuối ngày {date}",
    "Choose an owner": "Chọn Owner",
    "the document is wrong, not counted": "tài liệu sai, không tính",
    "the expected answer is wrong, not counted": "đáp án trong eval set sai, không tính",
    "everything else": "mọi trường hợp còn lại",
    "Choose a failure type": "Chọn Failure type",
    "Filled in from the judge's failing metric. Change it if the main cause is different.":
        "Điền sẵn theo metric bị judge cho Fail. Đổi lại nếu nguyên nhân chính khác.",
    "right document, wrong section or page": "đúng tài liệu, sai section hoặc trang",
    "One short sentence: why": "Một câu ngắn: vì sao",
    "Saving…": "Đang lưu…",
    "Disagreement (random 15)": "Disagreement (Random 15)",
    "not ready": "chưa có",

    # Calls line under Summary and failed runs
    "Calls: {n} chatbot turns": "Lượt gọi: {n} lượt chatbot",
    "{n} judge calls": "{n} lượt gọi judge",
    "{prompt} tokens in, {completion} out": "{prompt} token vào, {completion} token ra",
    "tokens not reported by the router": "router không báo số token",
    "answered by {models}": "model trả lời: {models}",
    "an unnamed model": "model không tên",
    "case text sent to {endpoint}": "nội dung câu đã gửi tới {endpoint}",
    "mock judge, no case text left the portal": "mock judge, không nội dung câu nào ra khỏi portal",
}
