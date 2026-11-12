"""The Eval sets pages (list, upload, one version) and the Runs and New run pages.

Follows the Vietnamese QC guide: a case is "câu", lock is "khoá". The New run labels Product, Set, Eval set version,
Milestone and Run type stay English, as the guide names them in its steps ("chọn product, set, version, build, milestone").
"""
VI = {
    # eval_sets.html, eval_set_view.html
    "Uploading…": "Đang tải lên…",
    "{file} · uploaded by {name} · {rows} rows": "{file} · {name} tải lên · {rows} dòng",
    "The file passed and is saved as Draft. Runs can use it after BA locks it.":
        "File đã qua kiểm tra và được lưu ở trạng thái Draft. Run dùng được sau khi BA khoá.",
    "Locked as {label}. Runs can use it now.": "Đã khoá thành {label}. Run dùng được ngay.",
    "{n} Safety case in {version} has no leak_strings. The code check for planted strings cannot run on them, so only the judge grades them.":
        "{n} câu Safety trong {version} không có leak_strings. Code dò chuỗi giả không chạy được trên câu này, nên chỉ judge chấm.",
    "{n} Safety cases in {version} have no leak_strings. The code check for planted strings cannot run on them, so only the judge grades them.":
        "{n} câu Safety trong {version} không có leak_strings. Code dò chuỗi giả không chạy được trên các câu này, nên chỉ judge chấm.",
    "Validation failed: {n} error.": "Kiểm tra không đạt: {n} lỗi.",
    "Validation failed: {n} errors.": "Kiểm tra không đạt: {n} lỗi.",
    "Fix and upload again. Nothing is saved until the file passes.": "Sửa rồi upload lại. File chưa đạt thì chưa lưu gì.",
    "Row": "Dòng",
    "Column": "Cột",
    "Error": "Lỗi",
    "Versions": "Các version",
    "Cases": "Số câu",
    "Status": "Trạng thái",
    "Locked by": "Người khoá",
    "Action": "Thao tác",
    "Lock as {label}? A locked version cannot change.": "Khoá thành {label}? Version đã khoá thì không sửa được nữa.",
    "Lock as {label}": "Lock thành {label}",
    "Locking…": "Đang khoá…",
    "No file uploaded yet. QC uploads the .xlsx here, then BA locks the version so official runs can use it.":
        "Chưa có file nào. QC upload file .xlsx ở đây, rồi BA khoá version để official run dùng được.",
    "Cases in this version": "Các câu trong version này",
    # runs.html
    "All products": "Tất cả product",
    "All sets": "Tất cả set",
    "All versions": "Tất cả version",
    "Filter": "Lọc",
    "Type": "Loại",
    "Acceptance after review": "Acceptance sau review",
    "vs previous official": "So với Official trước",
    "Done": "Xong",
    "No runs match these filters.": "Không có run nào khớp bộ lọc.",
    "Show all runs": "Xem tất cả run",
    "No runs yet. Upload a file on": "Chưa có run nào. Upload file ở trang",
    "; runs can use it after BA locks it.": "; run dùng được sau khi BA khoá.",
    # new_run.html
    "{label} · locked": "{label} · đã khoá",
    "No locked version yet. Upload on Eval sets, then BA locks it.":
        "Chưa có version đã khoá. Upload ở trang Eval sets, rồi BA khoá.",
    "{build} · on QA environment": "{build} · trên QA environment",
    "Choose a milestone": "Chọn milestone",
    "Run name": "Tên run",
    "{model}. Case text goes to {endpoint}": "{model}. Nội dung câu được gửi tới {endpoint}",
    "Mock judge. Its verdicts are not real, and no case text leaves the portal":
        "Mock judge. Kết quả chấm không phải thật, và không nội dung câu nào ra khỏi portal",
    "AI team confirmed Quick checks 100% Pass on {build}": "AI team đã xác nhận Quick checks Pass 100% trên {build}",
    "Cancel": "Huỷ",
    "Starting…": "Đang bắt đầu…",
}
