# app.py
# -*- coding: utf-8 -*-
import os
import io
import zipfile
import shutil
import tempfile
import subprocess
import hashlib
from pathlib import Path
import streamlit as st

# ===================== 工具函式 =====================

def human_size(num_bytes: int) -> str:
    if num_bytes < 1024.0: return f"{num_bytes:.2f} B"
    num_bytes /= 1024.0
    if num_bytes < 1024.0: return f"{num_bytes:.2f} KB"
    num_bytes /= 1024.0
    return f"{num_bytes:.2f} MB"

def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        return (p.returncode == 0, p.stdout if p.returncode == 0 else p.stderr)
    except Exception as e:
        return False, str(e)

FFMPEG_PATH = "ffmpeg" if command_exists("ffmpeg") else ""

# ==================== 核心轉檔邏輯 ====================

def convert_to_gif(input_data, settings, filename):
    if not FFMPEG_PATH:
        return False, None, "系統未安裝 ffmpeg"

    tmp_dir = tempfile.mkdtemp(prefix="gif_")
    input_path = os.path.join(tmp_dir, "in_" + filename)
    palette_path = os.path.join(tmp_dir, "palette.png")
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(input_data)

        fps = settings["fps"]
        width = settings["width"]
        style = settings["style"]

        if style == "細膩 (檔案大)":
            dither, colors = "sierra2_4a", 256
        elif style == "標準 (推薦)":
            dither, colors = "bayer", 128
        else:
            dither, colors = "none", 64

        cmd_palette = [
            FFMPEG_PATH, "-y", "-i", input_path,
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=max_colors={colors}",
            palette_path
        ]
        run_cmd(cmd_palette)

        cmd_conv = [
            FFMPEG_PATH, "-y", "-i", input_path, "-i", palette_path,
            "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither={dither}",
            output_path
        ]
        ok, err = run_cmd(cmd_conv)

        if ok:
            with open(output_path, "rb") as f:
                return True, f.read(), ""
        return False, None, err
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ==================== Streamlit 介面 ====================

st.set_page_config(page_title="GIF 4MB 批次轉檔工具", layout="wide")

if "files_data" not in st.session_state:
    st.session_state["files_data"] = {}
if "global_config" not in st.session_state:
    st.session_state["global_config"] = {"fps": 10, "width": 480, "style": "標準 (推薦)"}
if "config_ver" not in st.session_state:
    st.session_state["config_ver"] = 0
if "editing_now" not in st.session_state:
    st.session_state["editing_now"] = None

st.title("🎬 GIF 批次壓縮轉檔")

# --- 第一層：上傳（已移除快速預設區塊） ---
uploaded_files = st.file_uploader(
    "1. 上傳影片",
    type=["mp4", "mov", "m4v", "gif"],
    accept_multiple_files=True
)

st.divider()

# --- 第二層：批次管理 ---
if uploaded_files:
    # 同步檔案
    current_fids = []
    for f in uploaded_files:
        fid = hashlib.md5(f.name.encode()).hexdigest()
        current_fids.append(fid)
        if fid not in st.session_state["files_data"]:
            st.session_state["files_data"][fid] = {
                "name": f.name,
                "content": f.getvalue(),
                "settings": st.session_state["global_config"].copy(),
                "result": None
            }

    # 清理已刪除檔案
    st.session_state["files_data"] = {
        fid: info for fid, info in st.session_state["files_data"].items()
        if fid in current_fids
    }

    # 若目前編輯中的檔案被移除，清空選取
    if st.session_state["editing_now"] not in st.session_state["files_data"]:
        st.session_state["editing_now"] = None

    # 轉檔與下載按鈕列
    bc1, bc2 = st.columns([1, 1])
    with bc1:
        start_btn = st.button("🚀 開始批次轉檔", type="primary", use_container_width=True)
    with bc2:
        ready_results = {i["name"]: i["result"] for i in st.session_state["files_data"].values() if i["result"]}
        if len(ready_results) > 1:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for n, d in ready_results.items():
                    zf.writestr(Path(n).stem + ".gif", d)
            st.download_button(
                "📦 打包下載全部 (ZIP)",
                zip_buf.getvalue(),
                "all_gifs.zip",
                mime="application/zip",
                use_container_width=True
            )
        else:
            st.write("")

    if start_btn:
        progress_bar = st.progress(0)
        for i, (fid, info) in enumerate(st.session_state["files_data"].items()):
            ok, res, err = convert_to_gif(info["content"], info["settings"], info["name"])
            if ok:
                st.session_state["files_data"][fid]["result"] = res
            else:
                st.error(f"{info['name']} 轉檔失敗：{err}")
            progress_bar.progress((i + 1) / len(st.session_state["files_data"]))
        st.success("全部轉檔完成！")

    # 顯示清單
    st.write("---")
    for fid, info in st.session_state["files_data"].items():
        with st.container():
            # 檔名、大小、微調、下載
            c1, c2, c3, c4 = st.columns([4, 2, 1, 1])
            c1.write(f"📄 {info['name']}")

            if info["result"]:
                size = len(info["result"])
                size_str = human_size(size)
                c2.markdown(f"🔴 **{size_str}**" if size > 4 * 1024 * 1024 else f"🟢 {size_str}")
            else:
                c2.write("⏳ 待轉檔")

            if c3.button("⚙️ 微調", key=f"edit_btn_{fid}"):
                st.session_state["editing_now"] = fid
                st.rerun()

            if info["result"]:
                c4.download_button(
                    "💾 下載",
                    data=info["result"],
                    file_name=f"{Path(info['name']).stem}.gif",
                    mime="image/gif",
                    key=f"dl_each_{fid}",
                    use_container_width=True,
                )
            else:
                c4.write("")

            # 每支影片預覽改成摺疊/展開
            if info["result"]:
                is_editing_this = (st.session_state["editing_now"] == fid)
                with st.expander("👀 預覽", expanded=is_editing_this):
                    pv1, pv2 = st.columns([1.2, 2.8])
                    with pv1:
                        st.image(
                            info["result"],
                            caption=f"預覽 ({human_size(len(info['result']))})",
                            width=220
                        )
                    with pv2:
                        st.caption("可直接下載，或點「⚙️ 微調」調整後重新轉檔。")

            # 微調區直接出現在該影片下方（只顯示目前選中的）
            if st.session_state["editing_now"] == fid:
                st.markdown(f"### 🛠 正在調整: {info['name']}")

                ver = st.session_state["config_ver"]
                mc1, mc2, mc3, mc4, mc5 = st.columns([2, 2, 2, 1, 1])

                with mc1:
                    info["settings"]["fps"] = st.slider(
                        "流暢度 (FPS)",
                        1, 30,
                        info["settings"]["fps"],
                        key=f"fps_{fid}_{ver}"
                    )

                with mc2:
                    info["settings"]["width"] = st.number_input(
                        "寬度 (px)",
                        100, 1200,
                        info["settings"]["width"],
                        step=10,
                        key=f"w_{fid}_{ver}"
                    )

                with mc3:
                    styles = ["細膩 (檔案大)", "標準 (推薦)", "復古 (小體積)"]
                    info["settings"]["style"] = st.selectbox(
                        "畫質風格",
                        styles,
                        index=styles.index(info["settings"]["style"]),
                        key=f"s_{fid}_{ver}"
                    )

                with mc4:
                    st.write("")
                    if st.button("套用", key=f"apply_{fid}", type="primary", use_container_width=True):
                        ok, res, err = convert_to_gif(info["content"], info["settings"], info["name"])
                        if ok:
                            info["result"] = res
                            st.rerun()
                        else:
                            st.error(err)

                with mc5:
                    st.write("")
                    if st.button("關閉", key=f"close_edit_{fid}", use_container_width=True):
                        st.session_state["editing_now"] = None
                        st.rerun()

                # 微調區預覽（讓使用者不用再往上找）
                if info["result"]:
                    st.image(info["result"], width=320, caption="微調預覽")

        st.write("")

else:
    st.info("👋 你好！請上傳 MP4 影片，我們會幫你把它變成 4MB 以內的 GIF。")
