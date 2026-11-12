# VisionStudio

Tool kéo thả xử lý ảnh công nghiệp viết bằng Python và PyQt6. Mặc định chạy detect thật bằng webcam và
model YOLO11n (ONNX). Recipe mô phỏng vẫn có sẵn để thử khi không có phần cứng.

## Chạy

Cần Python 64-bit (PyQt6, OpenCV và onnxruntime không có bản 32-bit).

```bash
pip install -r requirements.txt
python main.py                                         # mở recipe dùng lần trước; lần đầu: webcam + YOLO
python main.py --recipe recipes/real_folder_yolo.json  # YOLO trên ảnh trong samples/ (không cần camera)
python main.py --recipe recipes/assy_conn_01.json      # camera và PLC mô phỏng
python main.py --headless --jobs 50 --recipe recipes/real_folder_yolo.json
python -m pytest tests -q                              # toàn bộ test + stress test (cần pytest)
```

Hướng dẫn từng chức năng: [docs/HUONG_DAN_SU_DUNG.md](docs/HUONG_DAN_SU_DUNG.md).

## Truyền kết quả ra ngoài và block Python tự tạo

- **Kênh truyền:** tab Thiết bị > Thêm thiết bị > Loại `comm`: `serial` (UART, RS-232, RS-485), `tcp`, `udp`, `ethercat`,
  `sim`. Node "Data Output" gửi kết quả theo mẫu, JSON hoặc CSV. PLC có thêm adapter `modbus_rtu` cho RS-485.
- **Block Python:** tab Studio > "Block Python…" để tự viết node bằng Python, chạy thử và lưu thành plugin.
- Chi tiết ở mục 18 và 19 của tài liệu hướng dẫn. Recipe mẫu: `recipes/demo_data_output.json`.

## Giao diện sáng / tối và ngôn ngữ

Hai nút trên thanh trên cùng đổi chế độ màu (Sáng / Tối) và ngôn ngữ (VI / EN); cũng có trong
Cài Đặt Hệ Thống > Cấu hình chung. Lựa chọn được lưu cho lần mở sau. Chuỗi gốc là tiếng Việt viết bằng
`t("...")`; bản tiếng Anh nằm trong `visionstudio/core/lang_en.py` và có test kiểm tra độ phủ.

## Tài khoản và phân quyền

Khi mở, ứng dụng ở trạng thái chưa đăng nhập với quyền của vai trò Operator. Bấm nút tài khoản ở góc
trên bên phải để đăng nhập, đổi tài khoản hoặc đăng xuất.

| Tài khoản | Mật khẩu mặc định | Vai trò |
| --- | --- | --- |
| `engineer` | `1111` | Engineer |
| `admin` | `0000` | Admin |
| `dev` | `dev1234` | Developer (toàn quyền, để test) |

Hãy đổi cả ba mật khẩu trước khi đưa tool ra khỏi bàn thử. Nên khóa hoặc xóa tài khoản `dev` trên máy
chạy ở xưởng.

- **Tạo tài khoản, khóa, xóa, đặt lại mật khẩu:** Cài Đặt Hệ Thống > Tài khoản & Phân quyền (cần quyền
  "Quản lý tài khoản và rule phân quyền").
- **Đặt rule:** tick vào bảng "Rule phân quyền theo vai trò". Có thể thêm vai trò mới, sao chép quyền
  từ một vai trò có sẵn.
- **Developer:** luôn có mọi quyền, cột Developer không chỉnh được. Chỉ Developer được cấp vai trò
  Developer hoặc sửa tài khoản Developer. Developer có thêm menu "Thử quyền của vai trò" để xem ứng
  dụng dưới quyền của vai trò khác mà không cần đăng xuất.
- Hệ thống từ chối thay đổi nào làm không còn tài khoản hoạt động có quyền quản lý tài khoản.
- Mật khẩu lưu dạng băm PBKDF2-SHA256 có salt trong `data/visionstudio.db`. Mọi lần đăng nhập, đăng
  nhập sai, tạo tài khoản và đổi rule đều được ghi vào audit trail.

## Dựng layout trong tab Studio

Cần đăng nhập tài khoản có quyền "Chỉnh sửa node, mở / lưu recipe" (Engineer, Admin, Developer). Khi
chưa có quyền, Studio hiện dải thông báo "Chế độ chỉ xem" kèm nút Đăng nhập.

| Việc | Cách làm |
| --- | --- |
| Tạo recipe trống | "Tạo mới", nhập mã và mô tả; danh sách thiết bị được giữ lại |
| Thêm node | Kéo từ danh sách bên trái vào sơ đồ, nhấp đúp, hoặc chuột phải > "Thêm node tại đây" |
| Nối cổng | Kéo từ cổng ra sang cổng vào, hoặc ngược lại; cổng hợp lệ sáng lên khi đang kéo |
| Di chuyển, chọn nhiều | Kéo node (bám lưới 10 px); kéo trên vùng trống để chọn theo vùng; Ctrl+A |
| Xóa node hoặc kết nối | Chọn rồi bấm Delete hoặc nút "Xóa"; chuột phải > "Ngắt mọi kết nối" |
| Nhân bản, sao chép | Ctrl+D, Ctrl+C / Ctrl+V |
| Hoàn tác, làm lại | Ctrl+Z, Ctrl+Y (thêm, xóa, nối, di chuyển, đổi tên, sửa tham số) |
| Xem sơ đồ | Lăn chuột để zoom, giữ nút giữa để di chuyển, F hoặc "Vừa khung", "Tự sắp xếp" |
| Sửa tham số node | Chọn node, sửa ở bảng bên phải |
| Lưu | "Lưu Recipe" (tăng phiên bản) hoặc "Lưu thành…"; recipe chưa lưu có dấu "● chưa lưu" |

Thay đổi trên sơ đồ được áp dụng cho engine ngay ở job kế tiếp, kể cả khi đang chạy.

## Detect thật

- **Model:** `models/yolo11n.onnx` là YOLO11n của Ultralytics (80 lớp COCO: person, car, bottle, ...),
  giấy phép AGPL-3.0. Để kiểm tra sản phẩm của nhà máy, cần huấn luyện model riêng rồi export ONNX
  (`yolo export model=best.pt format=onnx`) và chọn file đó trong node "YOLO Detector (ONNX)".
- **Camera:** tab Thiết bị > Sửa để đổi nguồn: số thứ tự webcam (0, 1, ...), URL RTSP của camera IP,
  hoặc một thư mục ảnh. Bấm "Lưu Recipe" ở tab Studio để giữ thay đổi.
- **Điều kiện OK/NG:** node "Count by Class", ví dụ `person=1` hoặc `bottle=6,cap=6`.
- **Node "YOLO Detector (Ultralytics .pt)":** chạy trực tiếp file `.pt`, cần `pip install ultralytics`
  (kéo theo PyTorch, nặng). Dùng khi phát triển; máy ở xưởng nên dùng node ONNX.

## Cấu trúc project

```
VisionStudio/
├── main.py                      # điểm vào: giao diện hoặc --headless
├── requirements.txt
├── README.md
├── recipes/
│   ├── real_webcam_yolo.json    # detect thật: webcam -> YOLO11n ONNX -> đếm
│   ├── real_folder_yolo.json    # detect thật trên ảnh trong samples/
│   ├── assy_conn_01.json        # mô phỏng: 2 camera -> sync -> detect -> đếm -> PLC
│   └── demo_data_output.json    # mô phỏng + node Data Output gửi kết quả qua kênh truyền
├── models/
│   └── yolo11n.onnx             # YOLO11n (COCO), AGPL-3.0
├── samples/
│   └── bus.jpg                  # ảnh thử cho recipe thư mục
├── plugins/
│   └── example_invert.py        # plugin mẫu: thả file .py vào đây là có node mới
├── docs/
│   └── HUONG_DAN_SU_DUNG.md     # hướng dẫn từng chức năng
├── tests/                       # python -m pytest tests -q
│   ├── conftest.py              # fixture dùng chung
│   ├── test_core.py             # lõi, tài khoản, bản dịch
│   ├── test_nodes.py            # từng loại node
│   ├── test_hardware.py         # camera, PLC
│   ├── test_storage.py          # cơ sở dữ liệu, lưu ảnh
│   ├── test_engine.py           # đồ thị, recipe, engine
│   ├── test_ui.py               # cả 7 tab giao diện
│   ├── test_comm.py             # kênh truyền, Data Output, Modbus
│   ├── test_userblock.py        # block Python tự tạo
│   └── test_stress.py           # stress test (--stress-scale N)
└── visionstudio/
    ├── core/                    # lõi, không phụ thuộc PyQt hay SDK hãng
    │   ├── schemas.py           # Frame, Detections, InspectionResult, kiểu cổng
    │   ├── node_base.py         # lớp Node, Param, registry, nạp plugin
    │   ├── graph.py             # đồ thị, kiểm tra kiểu/vòng lặp, Recipe JSON
    │   ├── executor.py          # chạy 1 job, đo thời gian từng node, vẽ overlay
    │   ├── engine.py            # vòng lặp job trong thread riêng, thống kê
    │   ├── storage.py           # SQLite, audit trail, kho ảnh, kho mẫu retrain
    │   ├── auth.py              # tài khoản, vai trò, rule phân quyền
    │   ├── i18n.py              # hàm t() chuyển ngôn ngữ
    │   ├── lang_en.py           # từ điển tiếng Anh
    │   └── userblock.py         # block Python tự tạo: kiểm tra, sinh mã, chạy thử, lưu
    ├── hardware/                # lớp trừu tượng phần cứng
    │   ├── camera.py            # Camera + adapter: sim, opencv (webcam/RTSP), folder
    │   ├── plc.py               # Plc, SimPlc, Modbus TCP, Modbus RTU
    │   ├── comm.py              # kênh truyền: serial (UART/RS-232/RS-485), TCP, UDP, EtherCAT
    │   └── manager.py           # tạo thiết bị theo khai báo trong recipe
    ├── nodes/                   # node dựng sẵn
    │   ├── source.py            # Camera
    │   ├── preprocess.py        # Multi-Cam Sync, Threshold, Blur, Crop, Grayscale, Resize, Rotate, CLAHE, Canny, Morphology, Color Mask
    │   ├── classic.py           # Contour Finder, Template Match, QR / Barcode Reader
    │   ├── measure.py           # Brightness, Sharpness, White Ratio, Detection Size, Detection Distance
    │   ├── ai.py                # Color Blob Detector, YOLO ONNX, YOLO Ultralytics .pt
    │   ├── logic.py             # Count by Class, Tolerance Check, Detection Filter, Presence Check, Combine Results
    │   └── output.py            # PLC Handshake, Save Image, Data Output
    └── ui/                      # giao diện PyQt6 (UI design)
        ├── theme.py             # bảng màu sáng / tối, stylesheet
        ├── context.py           # engine + store + phiên đăng nhập + kiểm tra quyền
        ├── widgets.py           # ImageView, Card, StatCard
        ├── main_window.py       # header, tab, footer
        ├── node_editor.py       # canvas kéo thả, cổng có kiểu, heatmap
        ├── studio_view.py       # Studio Editor & Heatmap
        ├── operator_view.py     # Operator Line
        ├── retrain_view.py      # AI Active Retrain
        ├── devices_view.py      # Thiết bị
        ├── history_view.py      # Inspection Logs
        ├── reports_view.py      # Xuất Báo Cáo
        ├── settings_view.py     # Cài Đặt Hệ Thống
        ├── users_view.py        # đăng nhập, tài khoản, bảng rule phân quyền
        └── block_editor.py      # hộp thoại soạn block Python
```

Dữ liệu chạy (DB, ảnh, kho mẫu) nằm trong `data/`, tự tạo khi chạy lần đầu.

## Mở rộng

**Thêm node:** tạo lớp kế thừa `Node`, gắn `@register`, khai báo `INPUTS`, `OUTPUTS`, `PARAMS`, viết
`process()`. Đặt file trong `plugins/` (xem `example_invert.py`). Panel thuộc tính tự sinh từ `PARAMS`.

**Thêm camera:** kế thừa `Camera` trong `hardware/camera.py`, viết `open()`, `_read()`, `close()`, rồi
gọi `register_camera("basler", BaslerCamera)`. Import SDK hãng bên trong `open()` để thiếu SDK không làm
hỏng ứng dụng. Trong recipe, đặt `"provider": "basler"` cho thiết bị.

**Thêm PLC:** kế thừa `Plc` trong `hardware/plc.py`, viết `connect()`, `read()`, `_write()`, rồi gọi
`register_plc("s7", S7Plc)`. Pipeline dùng tên logic `busy`, `done`, `result_ok`, `result_ng`.

**Khai báo thiết bị thật** (sửa trong tab Thiết bị, hoặc trực tiếp mục `devices` của recipe):

```json
"cam1": {"kind": "camera", "provider": "opencv", "name": "Webcam", "source": 0}
"cam1": {"kind": "camera", "provider": "opencv", "name": "IP cam", "source": "rtsp://192.168.1.50/stream"}
"cam1": {"kind": "camera", "provider": "folder", "name": "Ảnh mẫu", "path": "D:/samples"}
"plc1": {"kind": "plc", "provider": "modbus", "host": "192.168.0.10",
         "tags": {"busy": 0, "done": 1, "result_ok": 2, "result_ng": 3}}
```

## Trạng thái

| Hạng mục | Trạng thái |
| --- | --- |
| Lõi, node editor, 7 tab, lưu trữ, audit, xuất CSV/Excel/PDF | Đã chạy thử (test tự động + giao diện offscreen) |
| 22 node mới (tiền xử lý, cổ điển, đo lường, logic, lưu ảnh) | Đã thử từng node trên ảnh mẫu hoặc ảnh tổng hợp |
| Chế độ sáng / tối, ngôn ngữ Việt / Anh | Đã chạy thử trên giao diện offscreen, có test độ phủ bản dịch |
| Tài khoản, vai trò, rule phân quyền | Đã chạy thử (test tự động + giao diện offscreen) |
| YOLO Detector (ONNX) | Đã thử với YOLO11n trên ảnh mẫu, kết quả khớp với Ultralytics chạy cùng file ONNX |
| YOLO Detector (Ultralytics .pt) | Đã thử với yolo11n.pt trên CPU |
| Camera thư mục ảnh | Đã thử |
| Camera OpenCV (webcam/RTSP) | Luồng đọc đã thử bằng file video; chưa thử với webcam hay camera IP thật |
| PLC Modbus TCP và Modbus RTU | Đã thử với server / slave giả trên máy (khung truyền, CRC, địa chỉ trạm); chưa thử với PLC thật |
| Kênh serial, TCP, UDP và node Data Output | Đã thử với cổng loop-back, pty và socket nội bộ; chưa thử với thiết bị thật |
| Kênh EtherCAT | Viết theo API pysoem 1.1; chỉ thử được phần chép byte và báo lỗi, chưa thử với slave thật |
| Block Python tự tạo | Đã thử: tạo, chạy thử, lưu, sửa, xóa, chạy trong pipeline, phân quyền |
| Camera GenICam, Basler, Hikrobot; PLC S7, OPC UA | Chưa có adapter |
| Đồng bộ camera bằng PTP/trigger phần cứng, SAM 2, Anomaly, OCR | Chưa có |
| Fine-tune | Gọi lệnh `yolo` của Ultralytics nếu máy đã cài; chưa tự hot-swap model |