# 🗂 Smart Automatic File Organizer

A professional, real-time file organization system for Windows with **AI-powered Music Mood Classification**.

## ✨ Features
- **Real-time Monitoring**: Automatically organizes new files as they arrive using `watchdog`.
- **🤖 AI Music Moods**: Uses **Google Gemini AI** to classify songs into moods (Party, Romantic, Chill, etc.) by analyzing Title, Artist, and Genre metadata.
- **📁 Recursive Sorting**: Detects and organizes files even if they are deep inside sub-folders.
- **🛡️ Project Protection**: Automatically ignores vital project files like `.gitignore`, `package.json`, and `README.md`.
- **📅 Date-Based Layers**: Organizes Documents, Images, and Videos into `Year/Month` sub-folders.
- **↩ Undo Support**: Easily reverse the last 50 file movements if you make a mistake.
- **🎨 Modern GUI**: A sleek, dark-themed PyQt6 interface with live activity logs.

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- [Google Gemini API Key](https://aistudio.google.com/) (Required for AI features)

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/Automatic-Shorting-System.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

## 🛠️ Tech Stack
- **GUI**: PyQt6
- **Real-time API**: Watchdog
- **Metadata**: Mutagen
- **AI Engine**: Google Generative AI (Gemini Flash 1.5)

---
*Created by [Phenil](https://github.com/yourusername) - 2026*
