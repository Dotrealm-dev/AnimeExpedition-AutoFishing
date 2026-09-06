🐟 fishbait.dotrealm 🎣

Auto-fishing helper for Windows

fishbait.dotrealm เป็นโปรแกรมช่วยเล่นมินิเกมตกปลาแบบอัตโนมัติ โดยใช้ Computer Vision + Template Matching เพื่อตรวจจับตำแหน่งของปลาและแถบตกปลาจากหน้าจอ แล้วควบคุมการกดเมาส์ให้โดยอัตโนมัติ

⚠️ โปรแกรมนี้เป็นโปรเจกต์ทดลอง/เพื่อการศึกษา การใช้งานกับเกมออนไลน์อาจขัดต่อนโยบายหรือกฎของเกมนั้น ๆ

✨ Features
🎣 ตรวจจับปลาอัตโนมัติจากภาพหน้าจอ
📊 ตรวจจับ Fishing Bar ด้วย OpenCV
🖱️ ควบคุม Mouse ด้วย Windows SendInput
🧠 คำนวณการเคลื่อนที่ของปลาเพื่อช่วยติดตามตำแหน่ง
🎛️ มีระบบควบคุมแบบ PID-like
🔄 รองรับการคาดการณ์ตำแหน่งปลาเมื่อหาไม่เจอชั่วคราว
💤 มีระบบ IDLE สำหรับตรวจจับว่ามินิเกมจบแล้ว
⌨️ กด F8 เพื่อเริ่ม
⏸️ กด F10 เพื่อหยุด
🐟 มี Cute UI
🔍 มี Debug Window สำหรับดูการตรวจจับแบบ Real-time
🖥️ Requirements
Operating System
Windows 10 / 11
Python 3.10+ แนะนำ
Python Packages

ติดตั้ง dependencies ด้วย:

pip install numpy opencv-python mss

Tkinter โดยปกติจะมากับ Python สำหรับ Windows อยู่แล้ว
