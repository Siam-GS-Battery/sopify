# Dashboard Add-ons
- Bar Chart ต้องมีการเลือก Model ได้ (Token In และ Token Out) และ User สามารถเลือก Model ได้ว่าต้องการจะดู Token ของ Model ตัวไหน สามารถดูได้หลาย Model พร้อมกันได้ โดย Criteria การเลือก Model คือเคยมีการใช้งาน API Model นั้น อย่างน้อย 1 req

# Problems Statement
Hermes เขียน Code ได้ Quality ไม่มากพอ ติด Loop บ่อย ทั้งที่มีการใช้ Skills แล้ว
เราจึงอยากเพิ่มให้มีการใช้งาน Claude Code เป็นเครื่องมือในการให้ Hermes สามารถเรียก Calling ได้


# Claude Code Integration inside sandbox
เราจะมีการเพิ่ม docker image ของการใช้งาน Claude Code บน Docker Sandbox

1. Hermes
- Benefit : ทำงานบนฐานของการเชื่อมโยงข้อมูลข้าม Section + Persistant Memory
- Tasks : ในงานทั่วไปเราใช้ Hermes มาช่วย
    - ตอบคำถาม
    - Research
    - Gateway เชื่อมต่อ User + Cloud Gateway (พัฒนา Phases อื่น)
    - 24/7 Cron Job Running Tasks
    - Brainstorm

2. Claude Code
- Benefit : เก่งเรื่องการ Develop + Code Editing
- Tasks :
    - ในส่วน Part เรื่องจังหวะ Vibe Coding ในการทำ Design, Coding, Testing, Improvment
    - ใช้ตอน Coding เป็นหลัก

## Software Architecture

- Connection Activity : Claude Code Image <-- MCP Server --> Sopify
- Environment : Inside Sandbox


## Requirements
- Claude Code จะต้องมีการเข้าถึง Folder Directories /home/sopify/.hermes
- Claude Code จะต้องมีการ Setup ANTHROPIC_BASE_URL ได้ เนื่องจากเราจะไม่ได้ใช้ส่วนของ Anthropic Model เนื่องจาก Cost Model Anthropic สูง โดยใช้การ Setup Claude Code ได้ผ่าน Sopify Dashboard (จาก Hermes)


## Monitoring in Vibe Code Page
- เพิ่ม Card Monitoring ตรงส่วนหน้า Create Project ว่า
1. Token Usage Claude Code Calling
2. Token Usage Hermes Calling


## What i concered
1. เกิดการติด Loop เรียก API แล้วกิน Token มาก
2. หากเรา Acts Cluade Code As a Tools แปลว่าเรากำลังให้ Hermes ใช้ Claude Code เปรียบเสมือนมีคนนึงนั่งพิมพ์ Code แล้วมีอีกคนนึงเป็นตัวแทน คอยส่งงานไปให้ แล้วสรุปผลงานกลับมาให้ตัวแทน ซึ่งมันจะมีการกิน Token จากตัวแทน (Hermes) ในการส่งงานไปให้ Claude Code และกิน Token จาก Claude Code ในการส่งงานกลับมาให้ Hermes หรือไม่ ?
3. Claude Code จำ State ไม่ได้ว่าตัวเองทำงานถึงไหน
