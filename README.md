# ระบบจัดการพนักงาน (Employee Management System)

ระบบจัดการพนักงานที่ใช้ IBM Carbon Design System พร้อม Role-based Access Control

## 🎨 Features

- **3 ระดับผู้ใช้งาน:**
  - **พนักงานทั่วไป** - กรอกฟอร์มข้อมูลพนักงาน
  - **Admin** - ดูและจัดการข้อมูลพนักงานทั้งหมด
  - **ผู้ตรวจสอบ** - อนุมัติ/ปฏิเสธข้อมูลพนักงาน

- **UI/UX:**
  - IBM Carbon Design System (Minimal Tone สีฟ้า-ขาว)
  - Responsive Design
  - Modern และ Clean Interface

## 🛠 Tech Stack

### Frontend
- React 18
- IBM Carbon Design System (@carbon/react)
- React Router v6
- Axios

### Backend
- Node.js
- Express
- MongoDB (Mongoose)

## 📋 Prerequisites

ก่อนเริ่มต้น ต้องติดตั้งโปรแกรมเหล่านี้:

- Node.js (v16 หรือสูงกว่า)
- MongoDB (v5 หรือสูงกว่า)
- npm หรือ yarn

## 🚀 Installation

### 1. Clone repository

```bash
git clone <repository-url>
cd employee-management-system
```

### 2. ติดตั้ง Dependencies

#### วิธีที่ 1: ติดตั้งทั้งหมดพร้อมกัน
```bash
npm run install:all
```

#### วิธีที่ 2: ติดตั้งแยกส่วน
```bash
# ติดตั้ง root dependencies
npm install

# ติดตั้ง client dependencies
cd client
npm install

# ติดตั้ง server dependencies
cd ../server
npm install
```

### 3. ตั้งค่า Environment Variables

สร้างไฟล์ `.env` ในโฟลเดอร์ `server/`:

```bash
cd server
cp .env.example .env
```

แก้ไขไฟล์ `.env`:
```env
PORT=5000
MONGODB_URI=mongodb://localhost:27017/employee-management
```

### 4. เริ่มต้น MongoDB

ตรวจสอบว่า MongoDB กำลังรันอยู่:

```bash
# สำหรับ macOS (ถ้าใช้ Homebrew)
brew services start mongodb-community

# สำหรับ Linux
sudo systemctl start mongod

# สำหรับ Windows
net start MongoDB
```

## 🎯 Running the Application

### Development Mode

#### วิธีที่ 1: รันทั้ง Frontend และ Backend พร้อมกัน
```bash
npm run dev
```

#### วิธีที่ 2: รันแยกส่วน

**Terminal 1 - Backend:**
```bash
cd server
npm run dev
```

**Terminal 2 - Frontend:**
```bash
cd client
npm start
```

### Production Mode

```bash
# Build frontend
cd client
npm run build

# Start server
cd ../server
npm start
```

## 📱 Application URLs

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:5000
- **API Health Check:** http://localhost:5000/api/health

## 🔑 API Endpoints

### Employees

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/employees` | ดึงข้อมูลพนักงานทั้งหมด |
| GET | `/api/employees/:id` | ดึงข้อมูลพนักงานตาม ID |
| GET | `/api/employees/status/:status` | ดึงข้อมูลพนักงานตามสถานะ |
| POST | `/api/employees` | สร้างข้อมูลพนักงานใหม่ |
| PUT | `/api/employees/:id` | แก้ไขข้อมูลพนักงาน |
| PATCH | `/api/employees/:id/status` | อัพเดทสถานะพนักงาน |
| DELETE | `/api/employees/:id` | ลบข้อมูลพนักงาน |

### Employee Status Values
- `pending` - รอการตรวจสอบ
- `approved` - อนุมัติแล้ว
- `rejected` - ไม่อนุมัติ

## 📁 Project Structure

```
employee-management-system/
├── client/                    # Frontend React App
│   ├── public/
│   ├── src/
│   │   ├── pages/            # Page Components
│   │   │   ├── RoleSelection.js
│   │   │   ├── EmployeeDashboard.js
│   │   │   ├── AdminDashboard.js
│   │   │   └── ReviewerDashboard.js
│   │   ├── App.js
│   │   ├── index.js
│   │   └── index.scss
│   └── package.json
│
├── server/                    # Backend Node.js App
│   ├── server.js             # Main server file
│   ├── .env.example
│   └── package.json
│
├── package.json              # Root package.json
└── README.md
```

## 🎨 Design System

โปรเจคนี้ใช้ **IBM Carbon Design System** ซึ่งมีคุณสมบัติ:

- Minimal และ Professional
- สีหลัก: IBM Blue (#0f62fe)
- Typography: IBM Plex Sans
- Responsive Grid System
- Accessible Components

## 🔧 Troubleshooting

### MongoDB Connection Error
```bash
# ตรวจสอบว่า MongoDB กำลังรันอยู่
mongosh

# ถ้ายังไม่ได้เริ่ม MongoDB
brew services start mongodb-community  # macOS
sudo systemctl start mongod           # Linux
```

### Port Already in Use
```bash
# หา process ที่ใช้ port
lsof -i :3000  # Frontend
lsof -i :5000  # Backend

# Kill process
kill -9 <PID>
```

### Clear npm cache
```bash
npm cache clean --force
rm -rf node_modules package-lock.json
npm install
```

## 📝 Future Enhancements

- [ ] Authentication & Authorization
- [ ] Role-based Permissions
- [ ] File Upload (รูปโปรไฟล์)
- [ ] Export to Excel/PDF
- [ ] Email Notifications
- [ ] Advanced Search & Filters
- [ ] Dashboard Analytics
- [ ] Audit Logs

## 👨‍💻 Development

### การเพิ่ม Department ใหม่

แก้ไขไฟล์ `client/src/pages/EmployeeDashboard.js`:

```javascript
<Select id="department" ...>
  <SelectItem value="" text="เลือกแผนก" />
  <SelectItem value="IT" text="IT" />
  <SelectItem value="HR" text="HR" />
  // เพิ่มแผนกใหม่ที่นี่
  <SelectItem value="Operations" text="Operations" />
</Select>
```

## 📄 License

MIT License

## 🤝 Contributing

Contributions, issues และ feature requests ยินดีต้อนรับเสมอ!

---

สร้างด้วย ❤️ โดยใช้ React, Node.js และ IBM Carbon Design System
