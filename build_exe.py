"""用 PyInstaller 打包桌面版为单文件 exe。
    python build_exe.py
产物在 dist/PDF双语翻译器.exe
"""
import PyInstaller.__main__

PyInstaller.__main__.run([
    "gui.py",
    "--name=PDF双语翻译器",
    "--onefile",
    "--noconsole",
    "--collect-all=customtkinter",
    "--collect-all=matplotlib",
    "--collect-submodules=pdf_translator",
    "--hidden-import=PIL._tkinter_finder",
    "--noconfirm",
    "--clean",
])
