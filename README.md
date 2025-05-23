# Spotify Clone - Django + React

Ứng dụng web mô phỏng Spotify được xây dựng với Django cho backend API và Next.js cho frontend. Ứng dụng được đóng gói bằng Docker để dễ dàng thiết lập và triển khai.

## Cấu trúc dự án
- **Django** - Backend API được xây dựng với Django REST Framework
- **frontend** - Ứng dụng frontend được xây dựng với Next.js

## Yêu cầu
- Docker
- Docker Compose

## Bắt đầu

### 1. Clone repository
```bash
git clone <repository-url>
cd Spotify
```

### 2. Thiết lập biến môi trường
Tạo các biến môi trường cần thiết hoặc sử dụng các giá trị mặc định trong cấu hình Docker.

### 3. Khởi động ứng dụng
Chạy các container Docker bằng Docker Compose:
```bash
docker-compose up
```

Việc này sẽ khởi động cả dịch vụ backend Django và frontend Next.js.

- Backend API sẽ khả dụng tại: http://localhost:8000
- Frontend sẽ khả dụng tại: http://localhost:3000

### 4. Thiết lập cơ sở dữ liệu
Cơ sở dữ liệu sẽ tự động được thiết lập với các migration ban đầu. Nếu bạn cần chạy migrations thủ công:
```bash
docker exec -it spotify-backend-1 python manage.py migrate
```

## Xác thực API
Ứng dụng sử dụng xác thực token tùy chỉnh. Để xác thực:

1. Đăng nhập qua endpoint `/api/login/` với username và password
2. Sử dụng token được trả về trong các request tiếp theo với header: `Authorization: Token <your-token>`

## Phát triển

### Backend (Django)
- Các model API được định nghĩa trong `models.py`
- Các endpoint API được định nghĩa trong `views.py`
- Xác thực được quản lý trong `auth.py`

### Frontend (Next.js)
- Điểm khởi đầu là trong `_app.js`
- Các component ở trong thư mục `components`
- Styling sử dụng Tailwind CSS

## Dừng ứng dụng
Để dừng các container đang chạy:
```bash
docker-compose down
```

## Xử lý sự cố
Nếu bạn gặp các vấn đề liên quan đến cơ sở dữ liệu, bạn có thể cần reset các container:
```bash
docker-compose down -v  # Xóa cả volumes
docker-compose up
```