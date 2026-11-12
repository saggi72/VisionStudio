# VisionStudio - Hướng dẫn sử dụng

Tài liệu này mô tả từng chức năng của VisionStudio 0.1.0 theo thứ tự các tab trên giao diện.
Tên nút và nhãn được ghi theo giao diện tiếng Việt; phần "Ngôn ngữ" ở mục 2 cho biết cách chuyển sang tiếng Anh.

## Mục lục

1. Cài đặt và chạy
2. Giao diện chung: chế độ sáng/tối, ngôn ngữ, thanh trạng thái
3. Tài khoản và phân quyền
4. Tab Studio Editor & Heatmap: dựng pipeline
5. Danh mục node
6. Pipeline mẫu cho các bài toán thường gặp
7. Tab Thiết bị: camera và PLC
8. Tab Operator Line
9. Tab AI Active Retrain
10. Tab Inspection Logs
11. Tab Xuất Báo Cáo
12. Tab Cài Đặt Hệ Thống
13. Quy tắc kết quả OK / NG / ERROR
14. Mở rộng: viết node, thêm camera, thêm ngôn ngữ
15. Xử lý sự cố
16. Giới hạn hiện tại
17. Kiểm thử và stress test
18. Truyền kết quả ra ngoài: serial, RS-485, TCP, EtherCAT
19. Block Python tự tạo

## 1. Cài đặt và chạy

Cần Python 3.10 trở lên, bản 64-bit. PyQt6, OpenCV và onnxruntime không có bản cho Python 32-bit.

```bash
pip install -r requirements.txt
python main.py
```

| Lệnh | Tác dụng |
| --- | --- |
| `python main.py` | Mở giao diện với recipe dùng lần trước; lần đầu là webcam + YOLO11n |
| `python main.py --recipe recipes/real_folder_yolo.json` | YOLO trên ảnh trong `samples/`, không cần camera |
| `python main.py --recipe recipes/assy_conn_01.json` | Camera và PLC mô phỏng, không cần phần cứng |
| `python main.py --headless --jobs 50` | Chạy recipe không có giao diện, in kết quả từng job |
| `python main.py --data D:/vs_data` | Đổi thư mục dữ liệu (mặc định là `data/` cạnh `main.py`) |
| `python -m pytest tests -q` | Chạy bộ kiểm thử (cần `pip install pytest`) |

Thư mục dữ liệu chứa `visionstudio.db` (kết quả, audit, tài khoản, cài đặt), `archive/` (ảnh đã lưu),
`retrain_buffer/` (mẫu khó) và `error.log` (lỗi không mong đợi của giao diện).

## 2. Giao diện chung

Thanh trên cùng, từ trái sang phải: tên ứng dụng, recipe đang mở, 7 tab, nút chế độ màu, nút ngôn ngữ,
nút tài khoản, nút START / STOP.

**Chế độ sáng / tối.** Bấm nút "Sáng" hoặc "Tối" trên thanh trên cùng, hoặc chọn trong
Cài Đặt Hệ Thống > Cấu hình chung > Giao diện. Quy tắc màu: nền tối thì chữ sáng, nền sáng thì chữ tối,
áp dụng cho cả hộp thoại và menu. Vùng hiển thị ảnh camera luôn có nền đen và chữ sáng ở cả hai chế độ
để ảnh không bị chói. Chữ trên các nút có màu (xanh, đỏ, cam) luôn là màu trắng.

**Ngôn ngữ.** Bấm nút "EN" hoặc "VI" trên thanh trên cùng, hoặc chọn trong Cài Đặt Hệ Thống >
Cấu hình chung > Giao diện. Khi đổi chế độ màu hay ngôn ngữ, cửa sổ được dựng lại; phiên đăng nhập, tab
đang mở, recipe và trạng thái chạy được giữ nguyên, nhưng lịch sử Hoàn tác của Studio bị xóa.
Lựa chọn được lưu cho lần mở sau. Những phần không dịch: tên node (vốn là tiếng Anh), mã lý do
(ví dụ `MISSING_SCREW`), nội dung recipe và nhật ký audit đã ghi.

**Thanh trạng thái** ở đáy cửa sổ cho biết engine đang chạy hay dừng, số thiết bị kết nối được, tên trạm
và cycle time của job gần nhất.

**START / STOP** chạy và dừng vòng lặp kiểm tra. Mỗi vòng là một job: lấy ảnh, chạy pipeline, lưu kết quả.
Khoảng cách giữa hai job đặt ở Cài Đặt Hệ Thống > Chu kỳ trigger phần mềm.

## 3. Tài khoản và phân quyền

Khi mở, ứng dụng ở trạng thái chưa đăng nhập và có quyền của vai trò Operator.

| Tài khoản mặc định | Mật khẩu | Vai trò |
| --- | --- | --- |
| `engineer` | `1111` | Engineer |
| `admin` | `0000` | Admin |
| `dev` | `dev1234` | Developer |

Hãy đổi cả ba mật khẩu trước khi dùng thật, và khóa tài khoản `dev` trên máy ở xưởng.

**Đăng nhập, đăng xuất.** Bấm nút tài khoản ở góc trên bên phải > "Đăng nhập / đổi tài khoản…".
"Đăng xuất" đưa ứng dụng về trạng thái chưa đăng nhập.

**8 quyền** và giá trị mặc định:

| Quyền | Operator | Engineer | Admin | Developer |
| --- | --- | --- | --- | --- |
| Chạy / dừng recipe | có | có | có | có |
| Chỉnh sửa node, mở / lưu recipe | không | có | có | có |
| Thêm, sửa, kết nối lại thiết bị | không | có | có | có |
| Tạo, sửa, xóa block Python | không | không | có | có |
| Xuất dataset, fine-tune model | không | có | có | có |
| Xuất báo cáo, CSV | không | có | có | có |
| Cài đặt hệ thống, retention, dọn ảnh | không | không | có | có |
| Quản lý tài khoản và rule phân quyền | không | không | có | có |

**Quản lý** (Cài Đặt Hệ Thống > Tài khoản & Phân quyền, cần quyền "Quản lý tài khoản và rule phân quyền"):

- "Tạo tài khoản": nhập tên đăng nhập, họ tên, vai trò, mật khẩu (ít nhất 4 ký tự).
- "Sửa", "Đặt lại mật khẩu", "Khóa / Mở khóa", "Xóa": chọn một dòng trong bảng trước.
- "Đổi mật khẩu của tôi": tài khoản nào cũng dùng được, phải nhập mật khẩu hiện tại.
- Bảng "Rule phân quyền theo vai trò": tick để cấp quyền, có hiệu lực ngay.
- "Thêm vai trò": đặt tên và chọn vai trò để sao chép quyền. "Xóa vai trò" chỉ xóa được vai trò tự tạo
  và khi không còn tài khoản nào dùng.

**Các ràng buộc cố định:**

- Vai trò Developer luôn có mọi quyền; cột Developer không chỉnh được.
- Chỉ Developer được cấp vai trò Developer hoặc sửa tài khoản Developer.
- Không thể tự khóa hoặc tự xóa tài khoản đang đăng nhập.
- Thay đổi nào làm không còn tài khoản hoạt động có quyền quản lý tài khoản đều bị từ chối.

**Thử quyền (Developer).** Khi đăng nhập bằng tài khoản Developer, menu tài khoản có thêm
"Thử quyền của vai trò". Chọn một vai trò để xem ứng dụng dưới quyền của vai trò đó mà không cần đăng xuất;
chọn lại Developer để trở về.

## 4. Tab Studio Editor & Heatmap

Tab này dùng để dựng pipeline (layout) kiểm tra. Cần quyền "Chỉnh sửa node, mở / lưu recipe"; nếu không có,
Studio hiện dải "Chế độ chỉ xem" kèm nút Đăng nhập.

Màn hình có ba phần: danh sách node bên trái, sơ đồ ở giữa, bảng Inspector & Live Probe bên phải.

### 4.1 Recipe

Recipe là một file `.json` gồm danh sách thiết bị và sơ đồ node.

| Nút | Tác dụng |
| --- | --- |
| Sửa thông tin | Đổi mã (ID) và mô tả của recipe |
| Tạo mới | Tạo recipe trống, giữ lại danh sách thiết bị hiện tại |
| Mở… | Mở một file recipe |
| Lưu thành… | Lưu thành file mới; mã recipe lấy theo tên file, phiên bản bắt đầu lại từ 1 |
| Lưu Recipe | Lưu vào file hiện tại và tăng số phiên bản |

Recipe có thay đổi chưa lưu hiện dấu "● chưa lưu". Khi mở recipe khác hoặc đóng ứng dụng, chương trình hỏi
Lưu / Bỏ thay đổi / Hủy.

### 4.2 Thao tác trên sơ đồ

| Việc | Cách làm |
| --- | --- |
| Thêm node | Kéo từ danh sách vào sơ đồ; hoặc nhấp đúp; hoặc chuột phải vùng trống > "Thêm node tại đây" |
| Tìm node | Gõ vào ô "Tìm kiếm node..." |
| Nối hai node | Kéo từ một cổng sang cổng kia (chiều nào cũng được). Khi kéo, cổng nối được sáng lên, cổng không hợp lệ mờ đi |
| Di chuyển | Kéo node; node bám lưới 10 px |
| Chọn nhiều | Kéo trên vùng trống để khoanh vùng; Ctrl + nhấp; Ctrl+A chọn tất cả |
| Xóa | Chọn node hoặc đường nối rồi bấm Delete, nút "Xóa", hoặc chuột phải > "Xóa" |
| Ngắt kết nối của node | Chuột phải vào node > "Ngắt mọi kết nối" |
| Nhân bản | Ctrl+D hoặc nút "Nhân bản" |
| Sao chép, dán | Ctrl+C, Ctrl+V (dán cả đường nối giữa các node đã chép) |
| Hoàn tác, làm lại | Ctrl+Z, Ctrl+Y, hoặc hai nút trên thanh công cụ |
| Zoom | Lăn chuột |
| Di chuyển khung nhìn | Giữ nút giữa chuột và kéo |
| Vừa khung | Phím F hoặc nút "Vừa khung" |
| Tự sắp xếp | Xếp node từ trái sang phải theo luồng xử lý |

**Quy tắc nối:** chỉ nối được cổng ra với cổng vào cùng kiểu; mỗi cổng vào nhận một đường nối (nối đường
mới sẽ thay đường cũ); không được tạo vòng lặp. Màu cổng cho biết kiểu dữ liệu:

| Kiểu | Màu | Nội dung |
| --- | --- | --- |
| IMAGE | xanh dương | Ảnh (màu, xám hoặc nhị phân) |
| DETECTIONS | đỏ | Danh sách vật thể: lớp, điểm tin cậy, khung bao |
| MEASUREMENT | xanh lá | Một giá trị đo kèm đơn vị |
| RESULT | tím | Kết luận OK / NG / ERROR kèm lý do |

Dòng trạng thái trên thanh công cụ báo "Hợp lệ" hoặc lỗi cấu hình đầu tiên (ví dụ cổng vào chưa nối).
Node có lỗi được viền đỏ.

Thay đổi trên sơ đồ được áp dụng cho engine ở job kế tiếp, kể cả khi đang START. "Lưu Recipe" chỉ ghi ra file.

### 4.3 Inspector & Live Probe

Chọn một node để xem mô tả và sửa tham số ở bảng bên phải. Tham số đổi là có hiệu lực ở job kế tiếp.
Khi engine đang chạy, Live Probe hiện đầu ra của node đang chọn: ảnh sau xử lý, ảnh có khung detection,
hoặc ảnh kèm giá trị đo. Dùng nó để chỉnh ngưỡng và xem kết quả ngay.

### 4.4 Heatmap

Khi bật "Heatmap", mỗi node hiện thời gian chạy và tỉ lệ so với cả chu kỳ: viền xanh là dưới 20%, cam là
từ 20% đến 50%, đỏ là trên 50% và được ghi "Nút cổ chai". Đây là số đo thật của job gần nhất.

## 5. Danh mục node

### Nguồn ảnh & Đồng bộ (Source)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Multi-Cam Sync | cam1 (IMAGE), cam2 (IMAGE) | synced_pair (IMAGE) | Lệch tối đa (ms) | Ghép hai ảnh theo thời gian chụp và đặt cạnh nhau. Đây là ghép bằng phần mềm, không phải đồng bộ phần cứng. |
| Camera | không có | frame (IMAGE) | Thiết bị | Lấy một ảnh từ camera khai báo trong tab Thiết bị. |

### Tiền xử lý (Preprocess)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Threshold | image (IMAGE) | mask (IMAGE) | Phương pháp; Ngưỡng; Đảo | Tách ngưỡng ảnh xám thành ảnh nhị phân (Otsu, ngưỡng cố định hoặc thích nghi). |
| Gaussian Blur | image (IMAGE) | image (IMAGE) | Kích thước kernel | Làm mờ Gaussian để giảm nhiễu trước khi tách ngưỡng hoặc tìm biên. |
| Crop / ROI | image (IMAGE) | image (IMAGE) | X; Y; Rộng; Cao | Cắt một vùng chữ nhật của ảnh để chỉ xử lý vùng cần kiểm tra. |
| Grayscale | image (IMAGE) | image (IMAGE) | không có | Chuyển ảnh màu thành ảnh xám. |
| Resize | image (IMAGE) | image (IMAGE) | Tỉ lệ (%) | Đổi kích thước ảnh theo tỉ lệ phần trăm. Ảnh nhỏ hơn thì các bước sau chạy nhanh hơn. |
| Rotate / Flip | image (IMAGE) | image (IMAGE) | Xoay (độ); Lật | Xoay ảnh theo bội số 90 độ hoặc lật ảnh, dùng khi camera lắp nghiêng hay ngược. |
| Brightness / Contrast | image (IMAGE) | image (IMAGE) | Tương phản (x); Độ sáng (+/-) | Chỉnh độ tương phản (nhân) và độ sáng (cộng) của ảnh. |
| CLAHE | image (IMAGE) | image (IMAGE) | Giới hạn tương phản; Số ô lưới | Cân bằng tương phản cục bộ, làm rõ chi tiết khi ánh sáng không đều. Đầu ra là ảnh xám. |
| Canny Edge | image (IMAGE) | edges (IMAGE) | Ngưỡng thấp; Ngưỡng cao | Tìm biên bằng thuật toán Canny. Đầu ra là ảnh nhị phân, biên có màu trắng. |
| Morphology | mask (IMAGE) | mask (IMAGE) | Phép toán; Kích thước kernel; Số lần lặp | Phép hình thái trên ảnh nhị phân: open xóa đốm nhỏ, close lấp lỗ nhỏ, erode co, dilate nở. |
| Color Mask (HSV) | image (IMAGE) | mask (IMAGE) | H thấp; H cao; S thấp; S cao; V thấp; V cao | Giữ lại các điểm ảnh có màu nằm trong khoảng HSV. Đầu ra là ảnh nhị phân. H của OpenCV chạy từ 0 đến 179. |
| Invert (plugin mẫu) | image (IMAGE) | image (IMAGE) | Bật | Đảo sáng tối của ảnh. Đây là plugin mẫu để tham khảo cách viết node. |

### Thị giác cổ điển (Classic Vision)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Contour Finder | mask (IMAGE) | detections (DETECTIONS) | Tên lớp gán cho vùng; Diện tích tối thiểu (px); Diện tích tối đa (px) | Tìm các vùng trắng trên ảnh nhị phân và trả về khung bao của từng vùng, lọc theo diện tích. |
| Template Match | image (IMAGE) | detections (DETECTIONS) | File ảnh mẫu; Tên lớp; Điểm khớp tối thiểu; Số vị trí tối đa | Tìm vị trí giống ảnh mẫu nhất trong ảnh. Ảnh mẫu phải cùng tỉ lệ và cùng hướng với vật trong ảnh. |
| QR / Barcode Reader | image (IMAGE) | detections (DETECTIONS) | Loại mã; Dùng nội dung làm serial | Đọc mã QR và mã vạch 1D bằng OpenCV. Nội dung mã đầu tiên được dùng làm số serial của job. Mỗi mã đọc được là một detection có lớp là loại mã. |

### Trí tuệ nhân tạo (AI Vision)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Color Blob Detector | image (IMAGE) | detections (DETECTIONS) | Lớp cần tìm; Ngưỡng tin cậy; Diện tích tối thiểu (px) | Tìm connector và ốc của sản phẩm mô phỏng theo màu. Chỉ dùng với camera mô phỏng. |
| YOLO Detector (ONNX) | image (IMAGE) | detections (DETECTIONS) | File model .onnx; Tên lớp (để trống = đọc từ model); Chỉ giữ các lớp (để trống = tất cả); Ngưỡng tin cậy; NMS IoU; Backend | Phát hiện vật thể bằng model YOLO dạng ONNX. Chỉ cần onnxruntime; tên lớp đọc từ file model. |
| YOLO Detector (Ultralytics .pt) | image (IMAGE) | detections (DETECTIONS) | File model .pt; Chỉ giữ các lớp (để trống = tất cả); Ngưỡng tin cậy; NMS IoU; Kích thước ảnh suy luận; Thiết bị | Phát hiện vật thể bằng model YOLO dạng .pt qua thư viện ultralytics (PyTorch). Dùng khi phát triển. |

### Đo lường (Measure)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Mean Brightness | image (IMAGE) | value (MEASUREMENT) | không có | Đo độ sáng trung bình của ảnh (0 đến 255). Dùng để kiểm tra đèn chiếu hoặc phát hiện ảnh quá tối. |
| Sharpness (Focus) | image (IMAGE) | value (MEASUREMENT) | không có | Đo độ nét bằng phương sai Laplacian. Giá trị thấp nghĩa là ảnh mờ, ống kính lệch nét hoặc bị bẩn. |
| White Pixel Ratio | mask (IMAGE) | value (MEASUREMENT) | không có | Đo tỉ lệ phần trăm điểm trắng trên ảnh nhị phân. Dùng để kiểm tra mức phủ keo, mức đầy, vùng thiếu. |
| Detection Size | detections (DETECTIONS) | value (MEASUREMENT) | Lớp cần đo (để trống = bất kỳ); Đại lượng; Hệ số mm/px | Đo chiều rộng, chiều cao hoặc diện tích khung bao của detection lớn nhất (có thể lọc theo lớp). Nhập hệ số mm/px để đổi sang milimét. |
| Detection Distance | detections (DETECTIONS) | value (MEASUREMENT) | Lớp A; Lớp B; Hệ số mm/px | Đo khoảng cách giữa tâm của hai detection thuộc hai lớp (lấy detection có điểm cao nhất của mỗi lớp). Nhập hệ số mm/px để đổi sang milimét. |

### Logic

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| Count by Class | detections (DETECTIONS) | result (RESULT) | Số lượng mong đợi; Thừa cũng tính NG | Đếm detection theo lớp và so với số lượng mong đợi. Thiếu thì NG; thừa cũng NG nếu bật kiểm tra chặt. |
| Tolerance Check | value (MEASUREMENT) | result (RESULT) | Giá trị nhỏ nhất; Giá trị lớn nhất | So một giá trị đo với khoảng cho phép [min, max]. Trong khoảng là OK, ngoài khoảng là NG. |
| Detection Filter | detections (DETECTIONS) | detections (DETECTIONS) | Chỉ giữ các lớp (để trống = tất cả); Điểm tối thiểu; Diện tích tối thiểu (px); Diện tích tối đa (px) | Lọc detection theo lớp, điểm tin cậy và diện tích khung bao trước khi đếm hoặc đo. |
| Presence Check | detections (DETECTIONS) | result (RESULT) | Lớp bắt buộc có; Lớp bị cấm (lỗi) | Kiểm tra có / không: NG khi thiếu bất kỳ lớp bắt buộc nào, hoặc khi xuất hiện bất kỳ lớp bị cấm nào (ví dụ các lớp lỗi như scratch, dent). |
| Combine Results (AND) | a (RESULT), b (RESULT) | result (RESULT) | không có | Gộp hai kết quả thành một: OK khi cả hai đều OK, ERROR nếu có nhánh ERROR, còn lại là NG. Dùng trước PLC Handshake khi pipeline có nhiều phép kiểm. |

### Đầu ra & Truyền thông (Output)

| Node | Cổng vào | Cổng ra | Tham số | Công dụng |
| --- | --- | --- | --- | --- |
| PLC Handshake | result (RESULT) | không có | PLC | Ghi kết quả xuống PLC theo trình tự busy, result_ok / result_ng, done. Kết quả ERROR không bật bit nào. |
| Save Image | image (IMAGE) | không có | Thư mục lưu; Lưu mỗi N job; Định dạng | Lưu ảnh đi qua node vào một thư mục, mỗi N job một ảnh. Dùng để gom ảnh gốc làm dữ liệu huấn luyện. Thư mục tương đối được tính từ thư mục dữ liệu của ứng dụng. |
| Data Output | result (RESULT) | không có | Kênh truyền; Định dạng bản tin; Mẫu bản tin; Ký tự kết thúc; Bảng mã; Gửi khi | Gửi kết quả ra ngoài qua một kênh truyền khai báo trong tab Thiết bị: serial (UART, RS-232, RS-485), TCP, UDP hoặc EtherCAT. Bản tin dựng theo mẫu, JSON hoặc CSV. Trường dùng trong mẫu: {status} {ok} {serial} {job_no} {job_id} {reasons} {date} {time} và tên các giá trị đo (ví dụ {count_screw}); \x02 là ký tự mã 02. Gửi lỗi thì job báo ERROR. |

Nhóm "Block tự tạo (User)" xuất hiện khi bạn đã tạo block riêng (mục 18).

## 6. Pipeline mẫu cho các bài toán thường gặp

Mũi tên chỉ chiều nối từ cổng ra sang cổng vào.

| Bài toán | Pipeline |
| --- | --- |
| Đếm linh kiện bằng AI | Camera → YOLO Detector (ONNX) → Count by Class |
| Phát hiện lỗi bề mặt bằng AI | Camera → YOLO Detector (ONNX) → Presence Check (lớp bị cấm: scratch, dent) |
| Có / không có chi tiết theo màu | Camera → Color Mask (HSV) → Morphology → Contour Finder → Count by Class |
| Kiểm tra mức phủ keo, mức đầy | Camera → Crop / ROI → Threshold → White Pixel Ratio → Tolerance Check |
| Đo kích thước | Camera → Threshold → Contour Finder → Detection Size (mm/px) → Tolerance Check |
| Đo khoảng cách hai chi tiết | Camera → YOLO Detector → Detection Distance → Tolerance Check |
| Tìm chi tiết theo ảnh mẫu | Camera → Template Match → Count by Class (template=1) |
| Đọc mã QR làm serial | Camera → QR / Barcode Reader → Count by Class (qr=1) |
| Kiểm tra camera còn nét, đèn còn sáng | Camera → Sharpness (Focus) → Tolerance Check; Camera → Mean Brightness → Tolerance Check |
| Nhiều phép kiểm, báo PLC | Hai nhánh kết quả → Combine Results (AND) → PLC Handshake |
| Gửi kết quả cho máy in nhãn, robot, MES | ... → Count by Class → Data Output (kênh serial hoặc TCP) |
| Phép kiểm riêng của nhà máy | ... → block Python tự tạo → Data Output / PLC Handshake |
| Gom ảnh gốc để huấn luyện | Camera → Save Image (nối thêm, song song với nhánh kiểm tra) |

Cách lấy hệ số mm/px: chụp một vật có kích thước biết trước, đo số pixel của nó (dùng Detection Size với hệ số 1),
rồi lấy kích thước thật chia cho số pixel. Hệ số chỉ đúng khi camera, ống kính và khoảng cách chụp không đổi.

## 7. Tab Thiết bị

Mỗi thẻ là một camera, PLC hoặc kênh truyền (mục 18) khai báo trong recipe, kèm trạng thái (Connected, Error, No plugin), địa chỉ
và FPS hoặc thời gian ghi tag. Khi có lỗi, dòng cuối thẻ ghi nguyên nhân. Cần quyền "Thêm, sửa, kết nối lại thiết bị".

| Nút | Tác dụng |
| --- | --- |
| Thêm thiết bị | Mở hộp thoại khai báo camera hoặc PLC mới |
| Sửa / Xóa (trên thẻ) | Đổi cấu hình hoặc bỏ thiết bị khỏi recipe |
| Kết nối lại thiết bị | Đóng và mở lại mọi thiết bị, dùng sau khi cắm lại cáp |

Thay đổi thiết bị nằm trong recipe, nên cần bấm "Lưu Recipe" ở tab Studio để giữ lại.

**Adapter camera:**

| Adapter | Dùng cho | Tham số |
| --- | --- | --- |
| `opencv` | Webcam USB, camera IP (RTSP / HTTP) | Nguồn: số thứ tự webcam hoặc URL; độ phân giải (tùy chọn) |
| `folder` | Phát lại ảnh trong thư mục | Thư mục ảnh (png, jpg, bmp); tên file được dùng làm serial |
| `sim` | Camera mô phỏng | Góc nhìn top hoặc side |

**Trong hộp thoại camera:**

- "Dò webcam" thử mở webcam số 0 đến 5, liệt kê những số mở được kèm độ phân giải và điền số đầu tiên.
- "Thử kết nối và chụp một ảnh" mở camera theo cấu hình đang nhập, chụp một ảnh và hiện lên ngay trong hộp thoại,
  kèm kích thước ảnh hoặc thông báo lỗi. Cần bấm STOP trước khi thử.

Adapter `opencv` có một luồng đọc riêng và chỉ giữ ảnh mới nhất, nên mỗi job kiểm tra ảnh hiện tại chứ không phải
ảnh cũ trong bộ đệm. Nếu luồng ảnh bị ngắt, adapter tự kết nối lại sau mỗi giây.

**Adapter PLC:** `sim` (mô phỏng), `modbus` (Modbus TCP, ghi coil) và `modbus_rtu` (Modbus RTU qua cổng serial, thường là RS-485); hai loại Modbus cần `pip install pymodbus`. Địa chỉ trạm đặt ở ô "Địa chỉ trạm Modbus". Pipeline dùng
bốn tag logic `busy`, `done`, `result_ok`, `result_ng`; địa chỉ coil mặc định là 0, 1, 2, 3 và sửa được trong
mục `tags` của file recipe.

## 8. Tab Operator Line

Màn hình cho công nhân vận hành, không có chỗ chỉnh sửa.

- Khung lớn phía trên: kết quả job gần nhất (OK xanh, NG đỏ, ERROR cam), lý do, cycle time, số job và serial.
- Ảnh kiểm tra có vẽ khung detection và viền màu theo kết quả.
- Shift KPI: tổng số, số OK, NG, ERROR và tỉ lệ yield, tính trên toàn bộ dữ liệu đã lưu.

Tên tab trên thanh trên cùng cũng hiện kết quả gần nhất, để thấy được khi đang ở tab khác.

## 9. Tab AI Active Retrain

Gom ảnh mà model còn phân vân để huấn luyện lại.

1. Khi một job có detection với điểm nằm trong "vùng không chắc chắn" (mặc định 0,45 đến 0,65), ảnh gốc và nhãn
   do model sinh ra (nhãn giả) được lưu vào kho mẫu. Kho giữ tối đa 500 mẫu mới nhất. Hai ngưỡng và giới hạn này
   chỉnh trong Cài Đặt Hệ Thống.
2. "Xuất dataset YOLO" chép kho mẫu thành dataset định dạng YOLO trong `data/dataset/` kèm `data.yaml`.
3. Mở dataset bằng công cụ gán nhãn để sửa nhãn giả. Bước này bắt buộc: nhãn giả do chính model hiện tại sinh ra,
   train thẳng trên đó sẽ củng cố lỗi của model.
4. "Bắt đầu Fine-tune" gọi lệnh `yolo detect train` của Ultralytics nếu máy đã cài, và in log ra khung bên phải.
5. Sau khi train, export model sang ONNX (`yolo export model=best.pt format=onnx`) và chọn file mới trong node
   "YOLO Detector (ONNX)". Chương trình không tự thay model.

Cần quyền "Xuất dataset, fine-tune model".

## 10. Tab Inspection Logs

Bảng các job đã lưu, mới nhất ở trên: Job ID, thời gian, recipe, serial, kết quả, lý do, cycle time,
số detection, và có ảnh hay không.

- Lọc theo kết quả bằng hộp chọn (Tất cả, OK, NG, ERROR).
- Tìm theo serial hoặc lý do bằng ô tìm kiếm.
- Nhấp đúp một dòng có ảnh để xem ảnh đã lưu.
- "Xuất CSV" ghi toàn bộ bản ghi đã lưu ra file, không phụ thuộc bộ lọc đang chọn (cần quyền "Xuất báo cáo, CSV").

Ảnh NG và ERROR luôn được lưu dạng PNG. Ảnh OK chỉ lưu mẫu, mặc định 1 trong mỗi 20 ảnh, dạng JPEG.

## 11. Tab Xuất Báo Cáo

Bốn ô số: tổng sản phẩm, số OK, số NG, tỉ lệ yield. Biểu đồ Pareto liệt kê 10 lý do lỗi nhiều nhất kèm số lần và
tỉ lệ phần trăm. "Xuất Excel (.xlsx)" cần `pip install openpyxl`; "Xuất PDF báo cáo" không cần cài thêm gì.
Cả hai cần quyền "Xuất báo cáo, CSV". Số liệu lấy từ toàn bộ dữ liệu đã lưu trên trạm.

## 12. Tab Cài Đặt Hệ Thống

| Thẻ | Nội dung |
| --- | --- |
| Cấu hình chung | Tên trạm; chu kỳ trigger phần mềm (ms); hai cận của vùng không chắc chắn; chế độ màu và ngôn ngữ; danh sách loại node đã nạp và plugin bị lỗi |
| Tài khoản & Phân quyền | Xem mục 3 |
| Audit trail | Nhật ký: thời gian, tài khoản (vai trò), hành động, chi tiết. Ghi lại đăng nhập, đăng nhập sai, sửa sơ đồ, sửa tham số, lưu recipe, sửa thiết bị, đổi rule, start / stop |
| Lưu trữ & Retention | Số ngày giữ ảnh NG / ERROR (mặc định 90) và ảnh OK (mặc định 7); tỉ lệ lưu ảnh OK; số mẫu tối đa của kho retrain; nút "Dọn ảnh quá hạn ngay" |

Thông số trạm và lưu trữ cần quyền "Cài đặt hệ thống, retention, dọn ảnh". Chế độ màu và ngôn ngữ thì
tài khoản nào cũng đổi được.

## 13. Quy tắc kết quả OK / NG / ERROR

- **OK:** mọi phép kiểm đều đạt.
- **NG:** có ít nhất một phép kiểm không đạt. Lý do là mã như `MISSING_SCREW`, `EXTRA_PERSON`, `FOUND_SCRATCH`,
  `WIDTH_TOO_LOW`.
- **ERROR:** hệ thống không kết luận được, ví dụ mất camera, thiếu file model, sơ đồ chưa hợp lệ
  (`INVALID_GRAPH`), một node bị lỗi (`NODE_FAILED:<id node>`), hoặc sơ đồ không có node nào cho ra kết quả
  (`NO_RESULT_NODE`). ERROR không bao giờ được tính là OK.

Khi sơ đồ có nhiều node cho ra kết quả (nhiều nhánh kiểm tra), kết quả của job là tổng hợp của các kết quả cuối
nhánh: có ERROR thì ERROR, không thì có NG là NG, còn lại là OK. Node "PLC Handshake" chỉ ghi kết quả nối vào nó,
nên với nhiều nhánh hãy gộp bằng "Combine Results (AND)" trước khi nối vào PLC. Với kết quả ERROR, PLC Handshake
không bật `result_ok` lẫn `result_ng`.

## 14. Mở rộng

**Viết node mới.** Tạo một file `.py` trong thư mục `plugins/` (xem `plugins/example_invert.py`):

```python
from visionstudio.core.node_base import Node, Param, register
from visionstudio.core.schemas import PortType

@register
class MyNode(Node):
    TYPE = "my.node"                      # mã duy nhất
    TITLE = "My Node"
    DESC = "Mô tả hiện trong Inspector."
    CATEGORY = "Tiền xử lý (Preprocess)"
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("gain", "float", 1.0, "Hệ số", 0.1, 10.0)]

    def process(self, ctx, image):
        return {"image": image.with_image(image.image)}
```

Khởi động lại ứng dụng là node có trong danh sách. Bảng tham số tự sinh từ `PARAMS`; các kiểu tham số:
`int`, `float`, `bool`, `str`, `choice`, `file`, `device:camera`, `device:plc`. Plugin lỗi bị bỏ qua và được
liệt kê trong Cài Đặt Hệ Thống > Cấu hình chung.

**Thêm camera hoặc PLC của hãng.** Kế thừa `Camera` (viết `open`, `_read`, `close`) trong
`visionstudio/hardware/camera.py` rồi gọi `register_camera("ten_adapter", Lop)`; tương tự với `Plc` và
`register_plc`. Import SDK của hãng bên trong `open()` để máy không cài SDK vẫn chạy được ứng dụng.

**Thêm hoặc sửa bản dịch.** Chuỗi gốc là tiếng Việt, viết trong mã dưới dạng `t("...")`. Bản tiếng Anh nằm trong
`visionstudio/core/lang_en.py`. Bộ kiểm thử báo lỗi nếu có chuỗi chưa có bản dịch. Nhãn tham số, mô tả và nhóm
của node trong plugin cũng tra cùng từ điển đó; chuỗi không có bản dịch thì hiện nguyên tiếng Việt.

## 15. Xử lý sự cố

| Hiện tượng | Nguyên nhân và cách xử lý |
| --- | --- |
| `pip install` báo "No matching distribution" cho PyQt6 hoặc opencv | Đang dùng Python 32-bit. Cài Python 64-bit và tạo lại môi trường ảo |
| `ImportError: cannot import name '__version__'` | Thiếu file `visionstudio/__init__.py`. Cả 5 thư mục `visionstudio`, `core`, `hardware`, `nodes`, `ui` đều cần file `__init__.py` |
| Studio không cho sửa | Chưa đăng nhập tài khoản có quyền chỉnh sửa recipe (xem mục 3) |
| Thẻ camera báo "Không mở được nguồn '0'" | Không có webcam ở số đó hoặc ứng dụng khác đang dùng. Thử "Dò webcam" trong hộp thoại Sửa |
| Job báo ERROR "Thiếu thư viện onnxruntime" | Chạy `pip install onnxruntime` |
| Job báo ERROR "Không tìm thấy file model" | Kiểm tra đường dẫn trong node YOLO; đường dẫn tương đối tính từ thư mục chứa `main.py` |
| Job báo ERROR `NO_RESULT_NODE` | Sơ đồ chưa có node cho ra RESULT, ví dụ Count by Class hoặc Tolerance Check |
| YOLO không thấy vật cần kiểm | `yolo11n.onnx` chỉ biết 80 lớp COCO. Cần huấn luyện model riêng cho sản phẩm |
| Cycle time dài | Bật Heatmap để tìm node chậm; giảm kích thước ảnh bằng Resize hoặc Crop / ROI trước node AI |
| Ứng dụng gặp lỗi lạ | Xem `data/error.log` |

## 16. Giới hạn hiện tại

- Adapter webcam / RTSP mới được thử bằng file video, chưa thử với webcam và camera IP thật. Adapter Modbus chưa
  thử với PLC thật.
- Chưa có adapter cho camera công nghiệp GenICam, Basler, Hikrobot và cho PLC S7, OPC UA.
- Kênh EtherCAT chưa được thử với slave thật. Kênh serial, TCP, UDP và Modbus mới được thử với cổng loop-back, socket nội bộ và slave giả, chưa thử với thiết bị thật.
- Các kênh truyền chỉ gửi đi; chưa có nhận lệnh hay trigger từ bên ngoài qua serial hoặc TCP.
- Multi-Cam Sync ghép ảnh bằng phần mềm; chưa hỗ trợ trigger phần cứng hay PTP.
- Chưa có node OCR, phát hiện bất thường (anomaly) và phân vùng (segmentation).
- Đo kích thước dựa trên khung bao thẳng trục và một hệ số mm/px; chưa có hiệu chuẩn méo ống kính.
- Trigger là theo chu kỳ phần mềm; chưa có trigger từ PLC hay cảm biến.
- Sau khi fine-tune phải tự export và chọn model mới; chưa có thay model tự động.
- Audit trail và phân quyền chưa đủ để coi là tuân thủ FDA 21 CFR Part 11.
- Tài liệu này mới có bản tiếng Việt.

## 17. Kiểm thử và stress test

Bộ kiểm thử nằm trong `tests/`, chạy bằng pytest và không cần camera, PLC hay mạng. Test giao diện chạy ở chế độ
không hiện cửa sổ (Qt offscreen), nên chạy được cả trên máy không có màn hình.

```bash
pip install pytest psutil openpyxl
python -m pytest tests -q                                    # tất cả, khoảng 2 phút
python -m pytest tests -q --ignore tests/test_stress.py      # chỉ test chức năng, khoảng 40 giây
python -m pytest tests/test_stress.py -q -s                  # chỉ stress test, in số đo
python -m pytest tests/test_stress.py -q -s --stress-scale 5 # tải gấp 5 lần, khoảng 5 phút
python -m pytest tests/test_ui.py -q -k "studio or connect"  # chọn test theo tên
```

| File | Phạm vi |
| --- | --- |
| `conftest.py` | Fixture dùng chung: thư mục dữ liệu tạm, engine với recipe mô phỏng, cửa sổ chính đã đăng nhập |
| `test_core.py` | Đăng ký node, quy tắc nối, recipe, tài khoản và rule, YOLO trên ảnh mẫu, độ phủ bản dịch |
| `test_nodes.py` | Một test cho mỗi loại node (33 loại); thêm node mà không thêm test thì bộ test báo lỗi |
| `test_hardware.py` | Camera mô phỏng, thư mục ảnh, OpenCV (bằng file video), PLC, DeviceManager khi thiết bị hỏng |
| `test_storage.py` | Cài đặt, lưu và truy vấn kết quả, Pareto, lưu ảnh, retention, kho mẫu retrain, audit |
| `test_engine.py` | Đồ thị, file recipe, plugin, kết luận OK / NG / ERROR, vòng lặp engine, chế độ headless |
| `test_ui.py` | Cả 7 tab: chuyển tab, START / STOP, sáng / tối, ngôn ngữ, độ tương phản màu, đăng nhập, tài khoản, rule, Studio (kéo thả, nối, xóa, hoàn tác, chép dán, lưu / mở), thiết bị, lịch sử, báo cáo, retrain, cài đặt |
| `test_comm.py` | Kênh serial (cổng loop-back và pty), TCP, UDP, EtherCAT (phần không cần bus), node Data Output, Modbus RTU và TCP với slave giả |
| `test_userblock.py` | Block Python: kiểm tra khai báo, sinh mã, chạy thử, lưu / sửa / xóa, chạy trong pipeline, hộp thoại soạn block, quyền |
| `test_stress.py` | 14 kịch bản tải nặng, xem bảng dưới |

Các kịch bản stress (số trong ngoặc là tải ở mức mặc định; `--stress-scale N` nhân lên N lần):

| Kịch bản | Kiểm tra điều gì |
| --- | --- |
| Chạy dài (1.500 job) | Mọi job đều có kết luận và được lưu; cycle time không tăng dần; bộ nhớ không tăng |
| Sửa sơ đồ khi đang chạy (300 lần) | Đổi qua lại sơ đồ hợp lệ, sai, lỗi, rỗng từ luồng khác; engine không chết, không mất job |
| START / STOP liên tục (60 lần) và nạp lại recipe | Không sót luồng, số liệu khớp với cơ sở dữ liệu |
| STOP giữa một job chậm | STOP chờ job xong; không bao giờ có hai job chạy cùng lúc |
| Sơ đồ lớn (chuỗi 300 node, 60 nhánh song song) | Kiểm tra, sắp xếp và chạy được; kết luận nhiều nhánh đúng |
| Sửa sơ đồ ngẫu nhiên (4.000 thao tác) | Sơ đồ không bao giờ có vòng lặp hay cổng vào nhận hai đường nối |
| Cơ sở dữ liệu dùng đồng thời | 4 luồng truy vấn và ghi trong khi engine lưu job; không lỗi, dữ liệu toàn vẹn |
| Nhiều tài khoản (150) và vai trò (20) | Tạo, sửa, khóa, xóa; không xóa được người quản lý cuối cùng |
| Kho mẫu retrain (600 mẫu) | Kho không vượt giới hạn, ảnh và nhãn luôn đi theo cặp |
| Mở / đóng camera (40 lần) | Không sót luồng đọc ảnh |
| Giao diện khi job dồn dập | Engine chạy hết tốc độ trong khi chuyển tab liên tục; giao diện không bị treo |
| Trình soạn sơ đồ với 150 node | Dựng, tự sắp xếp, hoàn tác / làm lại, chép dán, xóa hết |
| Đổi sáng / tối và ngôn ngữ 24 lần khi đang chạy | Cửa sổ cũ bị hủy thật, engine vẫn chạy, phiên đăng nhập được giữ |
| Đăng nhập / đăng xuất 30 vòng kèm đổi rule | Quyền trên giao diện luôn khớp với tài khoản |

Stress test chạy trên thiết bị mô phỏng, nên đo sức chịu của phần mềm chứ chưa đo camera, PLC và model thật.
Nếu máy không cài `psutil`, phần kiểm tra bộ nhớ được bỏ qua.

## 18. Truyền kết quả ra ngoài: serial, RS-485, TCP, EtherCAT

Có hai việc phải làm: khai báo một **kênh truyền** trong tab Thiết bị, rồi đặt node **Data Output** vào sơ đồ.

### 18.1 Khai báo kênh truyền

Tab Thiết bị > "Thêm thiết bị" > Loại = `comm`, rồi chọn adapter:

| Adapter | Dùng cho | Tham số | Cần cài |
| --- | --- | --- | --- |
| `serial` | UART (TTL qua bộ USB-UART), RS-232, RS-485 | Cổng serial (nút "Dò cổng" liệt kê các cổng COM), tốc độ baud, bit dữ liệu, parity, bit dừng, "RS-485 điều khiển RTS" | `pip install pyserial` |
| `tcp` | Thiết bị có cổng Ethernet đang lắng nghe (máy in, robot, PC khác) | Địa chỉ IP, cổng | không |
| `udp` | Gửi bản tin không cần kết nối | Địa chỉ IP, cổng | không |
| `ethercat` | Một slave EtherCAT | Card mạng, vị trí slave, byte bắt đầu, chu kỳ trao đổi | `pip install pysoem` |
| `sim` | Thử pipeline khi chưa có phần cứng | không có | không |

Nút "Thử kết nối và gửi một bản tin" mở kênh theo cấu hình đang nhập và gửi dòng `VISIONSTUDIO TEST`. Dùng nó cùng một
phần mềm terminal ở đầu nhận để kiểm tra dây và thông số trước khi chạy. Thẻ của kênh trong tab Thiết bị hiện số bản tin
và số byte đã gửi.

**UART, RS-232, RS-485 khác nhau thế nào.** Với phần mềm, cả ba đều là một cổng COM và cùng adapter `serial`; khác nhau ở
mức điện áp và cách đấu dây, tức là ở bộ chuyển đổi bạn cắm vào máy tính. Thông số (baud, parity, bit dừng) phải giống
thiết bị nhận. Ô "RS-485 điều khiển RTS" chỉ cần tick khi bộ chuyển đổi RS-485 không tự đổi chiều thu / phát; phần lớn bộ
USB-RS485 tự đổi chiều và không cần tick. Nếu thiết bị nhận nói Modbus RTU trên RS-485, hãy dùng adapter PLC `modbus_rtu`
và node PLC Handshake thay vì gửi chuỗi ký tự.

**EtherCAT.** EtherCAT trao đổi dữ liệu theo chu kỳ chứ không gửi từng bản tin. Adapter này làm master cho một slave: một
luồng nền trao đổi dữ liệu mỗi chu kỳ, và mỗi lần node Data Output gửi, các byte của bản tin được chép vào vùng dữ liệu đầu
ra của slave, bắt đầu từ "Byte bắt đầu"; bản tin dài hơn vùng này bị cắt. Cần một cổng mạng dành riêng và quyền quản trị
(trên Windows cần cài Npcap). Phần này viết theo API của pysoem nhưng **chưa được thử với slave thật**; mình chỉ kiểm tra
được việc chép byte và việc báo lỗi khi không có slave. Với dây chuyền dùng PLC làm master EtherCAT, cách chắc chắn hơn là
gửi kết quả cho PLC qua Modbus hoặc TCP rồi để PLC đưa lên bus.

### 18.2 Node Data Output

Nối cổng `result` của node vào một node cho ra kết quả (Count by Class, Tolerance Check, Combine Results...).

| Tham số | Ý nghĩa |
| --- | --- |
| Kênh truyền | Kênh đã khai báo trong tab Thiết bị |
| Định dạng bản tin | `template` (theo mẫu), `json`, hoặc `csv` (ngày, giờ, số job, serial, kết quả, lý do) |
| Mẫu bản tin | Chuỗi có các trường trong ngoặc nhọn, ví dụ `{status},{serial},{reasons}` |
| Ký tự kết thúc | CRLF, LF, CR hoặc không có |
| Bảng mã | `ascii` (ký tự ngoài ASCII được thay bằng `?`) hoặc `utf-8` |
| Gửi khi | `always` (mọi job), `ok_only`, `ng_only`, `not_ok` (NG và ERROR) |

Các trường dùng được trong mẫu:

| Trường | Giá trị |
| --- | --- |
| `{status}` | OK, NG hoặc ERROR |
| `{ok}` | 1 khi OK, 0 khi khác |
| `{reasons}` | Các mã lý do, cách nhau bằng dấu `;` |
| `{serial}` | Serial của sản phẩm (từ camera hoặc mã QR) |
| `{job_no}`, `{job_id}` | Số job (7) và mã job (JOB-00007) |
| `{date}`, `{time}` | Ngày và giờ gửi |
| tên giá trị đo | Mọi giá trị có trong kết quả, ví dụ `{count_screw}`, `{width}`, `{brightness}` |

Trong mẫu có thể viết `\r`, `\n`, `\t` và `\xHH` cho ký tự điều khiển, ví dụ `\x02{status}\x03` để bọc bản tin giữa STX và
ETX. Mẫu dùng một trường không tồn tại thì job báo ERROR và thông báo liệt kê các trường có sẵn. Gửi thất bại (đứt cáp, cổng
bị đóng) cũng làm job báo ERROR, để không có kết quả nào bị mất mà không ai biết.

Recipe mẫu `recipes/demo_data_output.json` có sẵn một node Data Output trên kênh mô phỏng; đổi adapter của `com1` sang
`serial` hoặc `tcp` trong tab Thiết bị là gửi ra thiết bị thật. Khi cần bản tin nhị phân hoặc giao thức riêng, viết một
block Python (mục 19) và gọi `ctx.devices.comm("com1").send(bytes(...))`.

**Thêm bus khác** (CAN, MQTT, gateway PROFINET...): kế thừa `Channel` trong `visionstudio/hardware/comm.py`, viết `open`,
`_send`, `close`, rồi gọi `register_comm("ten", Lop)`. Có thể đặt lớp đó trong một file ở `plugins/`.

## 19. Block Python tự tạo

Khi các node có sẵn không đủ, bạn tự viết phép xử lý bằng Python ngay trong ứng dụng. Mỗi block là một node bình thường:
có cổng, có tham số chỉnh trong Inspector, dùng lại được trong mọi recipe.

Cần quyền "Tạo, sửa, xóa block Python". Mặc định chỉ Admin và Developer có quyền này, vì mã trong block chạy với toàn quyền
của ứng dụng trên máy tính (đọc ghi file, mạng, thiết bị). Cấp cho vai trò khác trong bảng rule phân quyền nếu cần.

### 19.1 Tạo block

1. Tab Studio > "Block Python…" > "Block mới".
2. Nhập tên hiển thị. Mã block được sinh từ tên (ví dụ "Kiểm tra diện tích" thành `kiem_tra_dien_tich`) và không đổi được
   sau khi lưu, vì recipe nhận ra block qua mã này.
3. Khai báo cổng vào, cổng ra và tham số bằng nút `+` / `-`. Tên dùng chữ thường không dấu, số và `_`.
4. Viết mã vào khung soạn thảo. Dòng màu xanh phía trên cho biết chữ ký hàm, ví dụ
   `def run(self, ctx, params, dets):`; bạn chỉ viết phần thân. "Tạo lại mã mẫu" sinh một đoạn mã khởi đầu khớp với các
   cổng đang khai báo.
5. "Chạy thử" chạy block một lần trên dữ liệu mẫu (ảnh của job gần nhất nếu có) và in đầu vào, đầu ra hoặc lỗi kèm số dòng.
6. "Lưu block". Block chỉ được lưu khi chạy thử thành công. Nó xuất hiện ngay trong danh sách node, nhóm "Block tự tạo".

### 19.2 Viết mã

Mỗi cổng vào là một biến cùng tên:

| Kiểu cổng | Biến nhận được |
| --- | --- |
| IMAGE | `x.image` là ảnh numpy (BGR hoặc xám); `x.meta` là thông tin kèm theo |
| DETECTIONS | `x.items` là danh sách, mỗi phần tử có `cls_name`, `score`, `box = (x1, y1, x2, y2)` |
| MEASUREMENT | `x.value` là số đo, `x.unit` là đơn vị, `x.name` là tên |
| RESULT | `x.status` là "OK" / "NG" / "ERROR", `x.reasons` là danh sách lý do, `x.values` là các giá trị đo |

Mã phải `return` một dict có đủ các cổng ra. Giá trị trả về có thể là kiểu Python thường:

| Kiểu cổng ra | Được phép trả về |
| --- | --- |
| IMAGE | Ảnh numpy |
| DETECTIONS | Danh sách `Detection("ten_lop", diem, (x1, y1, x2, y2))` |
| MEASUREMENT | Một số, hoặc `Measurement("ten", gia_tri, "mm")` |
| RESULT | `True` (OK) / `False` (NG), hoặc `InspectionResult("NG", ["MA_LY_DO"], {"ten": gia_tri})` |

Có sẵn trong mã: `cv2`, `np`, `math`, `params["ten_tham_so"]`, `ctx.shared["serial"]`, `ctx.job_no`, `ctx.devices`.

Ví dụ, block có cổng vào `dets` (DETECTIONS), cổng ra `result` (RESULT) và `area` (MEASUREMENT), tham số `min_area` (float):

```python
areas = [(d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) for d in dets.items]
biggest = max(areas, default=0)
return {"result": biggest >= params["min_area"], "area": biggest}
```

### 19.3 Điều cần biết

- Mã ném ra lỗi khi đang chạy thì job đó báo ERROR kèm tên node và nội dung lỗi; job không bao giờ thành OK vì block hỏng.
- Trả về sai kiểu hoặc thiếu cổng ra cũng là ERROR, với thông báo nêu rõ cổng nào.
- Sửa block rồi lưu là có hiệu lực ở job kế tiếp. Nếu bạn bỏ hoặc đổi kiểu một cổng, các đường nối vào cổng đó bị gỡ và
  Studio báo số đường nối đã gỡ.
- Mỗi block là một file `plugins/user_<mã>.py`. Chép recipe sang máy khác thì phải chép cả các file này; thiếu file thì node
  báo "Thiếu plugin" và job báo ERROR.
- Xóa block khi recipe còn dùng nó cũng dẫn tới "Thiếu plugin"; hộp thoại xóa có cảnh báo.
- Mỗi lần lưu và xóa block được ghi vào audit trail.
- Block chạy trong luồng xử lý của job: một block chậm làm cả chu kỳ chậm theo. Heatmap cho thấy thời gian của từng block.