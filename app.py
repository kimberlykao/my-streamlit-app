# app.py
# -*- coding: utf-8 -*-
import os
import io
import zipfile
import shutil
import tempfile
import subprocess
import hashlib
import base64
from pathlib import Path

import streamlit as st

# ===================== 公用工具 =====================

def human_size(num_bytes: int) -> str:
    try:
        num_bytes = float(num_bytes)
    except Exception:
        num_bytes = 0.0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"

def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        if p.returncode == 0:
            return True, p.stdout
        else:
            return False, p.stderr
    except Exception as e:
        return False, str(e)

# ========== ffmpeg / gifsicle 指令查找 ==========

def find_ffmpeg() -> str:
    if command_exists("ffmpeg"):
        return "ffmpeg"
    return ""

def find_gifsicle() -> str:
    if command_exists("gifsicle"):
        return "gifsicle"
    return ""

FFMPEG_PATH = find_ffmpeg()
GIFSICLE_PATH = find_gifsicle()
FFMPEG_AVAILABLE = bool(FFMPEG_PATH)
GIFSICLE_AVAILABLE = bool(GIFSICLE_PATH)

# ==================== 轉檔邏輯 ====================

def safe_convert(
    input_data: bytes,
    fps: int,
    target_width: int,
    dither: str,
    compress: str,
    is_gif: bool,
) -> tuple[bool, bytes | None, str]:
    """
    使用 ffmpeg 轉檔為 GIF，並試圖用較安全的參數避免崩潰。
    """
    if not FFMPEG_AVAILABLE:
        return False, None, "系統未安裝 ffmpeg，無法轉檔。"

    tmp_dir = tempfile.mkdtemp(prefix="gifconv_")
    input_path = os.path.join(tmp_dir, "input")
    if is_gif:
        input_path += ".gif"
    else:
        input_path += ".mp4"
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(input_data)

        scale_filter = f"scale={target_width}:-1:flags=lanczos"

        # 根據畫質模式設定 palettegen/paletteuse
        if dither == "none":
            dither_option = "dither=none"
        elif dither == "sierra2_4a":
            dither_option = "dither=sierra2_4a"
        else:
            dither_option = "dither=bayer"

        # 壓縮程度調整 palettegen 最大彩色數
        if compress == "保守":
            max_colors = 128
        elif compress == "強化":
            max_colors = 80
        elif compress == "激進":
            max_colors = 64
        else:
            max_colors = 96  # 平衡

        # 建立 palette 中繼檔
        palette_path = os.path.join(tmp_dir, "palette.png")
        cmd_palette = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-vf", f"{scale_filter},fps={fps},palettegen=max_colors={max_colors}",
            palette_path,
        ]
        ok, err = run_cmd(cmd_palette)
        if not ok:
            return False, None, f"建立調色盤失敗：\n{err}"

        # 使用 palette 把影片轉成 GIF
        cmd_gif = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-i", palette_path,
            "-lavfi", f"{scale_filter},fps={fps},paletteuse={dither_option}",
            "-loop", "0",
            output_path,
        ]
        ok, err = run_cmd(cmd_gif)
        if not ok:
            return False, None, f"轉檔 GIF 失敗：\n{err}"

        if not os.path.exists(output_path):
            return False, None, "轉檔後找不到 GIF 檔案。"

        with open(output_path, "rb") as f:
            gif_bytes = f.read()
        return True, gif_bytes, ""
    except Exception as e:
        return False, None, f"轉檔過程異常：{e}"
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

def reencode_gif(
    gif_bytes: bytes,
    fps: int,
    target_width: int,
    dither: str,
    compress: str,
) -> tuple[bool, bytes | None, str]:
    """
    使用 ffmpeg 重新壓縮已存在的 GIF（控制 FPS / 寬度 / palette）。
    """
    if not FFMPEG_AVAILABLE:
        return False, None, "系統未安裝 ffmpeg，無法轉檔。"

    tmp_dir = tempfile.mkdtemp(prefix="gifreenc_")
    input_path = os.path.join(tmp_dir, "input.gif")
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(gif_bytes)

        scale_filter = f"scale={target_width}:-1:flags=lanczos"

        if dither == "none":
            dither_option = "dither=none"
        elif dither == "sierra2_4a":
            dither_option = "dither=sierra2_4a"
        else:
            dither_option = "dither=bayer"

        if compress == "保守":
            max_colors = 128
        elif compress == "強化":
            max_colors = 80
        elif compress == "激進":
            max_colors = 64
        else:
            max_colors = 96

        palette_path = os.path.join(tmp_dir, "palette.png")
        cmd_palette = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-vf", f"{scale_filter},fps={fps},palettegen=max_colors={max_colors}",
            palette_path,
        ]
        ok, err = run_cmd(cmd_palette)
        if not ok:
            return False, None, f"GIF 建立調色盤失敗：\n{err}"

        cmd_gif = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-i", palette_path,
            "-lavfi", f"{scale_filter},fps={fps},paletteuse={dither_option}",
            "-loop", "0",
            output_path,
        ]
        ok, err = run_cmd(cmd_gif)
        if not ok:
            return False, None, f"GIF 重新編碼失敗：\n{err}"

        if not os.path.exists(output_path):
            return False, None, "GIF 重新編碼後找不到成品。"

        with open(output_path, "rb") as f:
            out_bytes = f.read()
        return True, out_bytes, ""
    except Exception as e:
        return False, None, f"GIF 重新編碼過程異常：{e}"
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

# ==================== Streamlit 介面 ====================

st.set_page_config(page_title="GIF 轉檔工具", layout="wide")

st.markdown(
    """
<style>
/* 整體背景微灰，內容區卡片感 */
.main {
    background-color: #f7f7f9;
}

/* 左右欄間距、卡片樣式 */
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 1.2rem;
}

/* 左側卡片 */
.left-card {
    background: white;
    border-radius: 12px;
    padding: 16px 18px;
    border: 1px solid #e2e2ea;
}

/* 右側卡片 */
.right-card {
    background: white;
    border-radius: 12px;
    padding: 16px 18px;
    border: 1px solid #e2e2ea;
}

/* 控制項區塊 */
.controls {
    border-radius: 8px;
    background: #fafafa;
    padding: 8px 10px;
    margin-bottom: 6px;
}

/* 預覽區塊標題 */
.section-title {
    font-weight: 600;
    font-size: 14px;
    margin: 10px 0 4px;
}

/* 小字說明 */
.small-text {
    font-size: 12px;
    color: #666;
}

/* 檔案列表樣式 */
.file-item {
    border-radius: 8px;
    padding: 4px 8px;
    margin-bottom: 4px;
}
.file-item.selected {
    background: #e5f0ff;
    border: 1px solid #8ab4ff;
}
.file-item.unselected {
    background: #f5f5f7;
}

/* 二級標題與分隔線 */
h1, h2, h3 {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

/* 說明區域 */
.note-box {
    background: #fff9e6;
    border-radius: 8px;
    padding: 8px 10px;
    border: 1px solid #ffe9a3;
    font-size: 13px;
}

/* 移除預設的 block 下方距離，縮短整體高度 */
.stMarkdown { margin-bottom: 4px !important; }

/* 右欄下載置中 */
.center { text-align: center; }

/* 影片原始尺寸小字 */
.dim-note { font-size: 12px; color: #666; margin: 6px 4px 0 4px; }
</style>
""",
    unsafe_allow_html=True,
)

# ---- 狀態 ----
if "selected_video_id" not in st.session_state:
    st.session_state["selected_video_id"] = None
if "global_settings" not in st.session_state:
    st.session_state["global_settings"] = {"fps": 10, "width": 800, "dither": "bayer", "compress": "平衡"}
if "video_settings" not in st.session_state:
    st.session_state["video_settings"] = {}
if "preview_cache" not in st.session_state:
    st.session_state["preview_cache"] = {}
if "final_cache" not in st.session_state:
    st.session_state["final_cache"] = {}
if "durations" not in st.session_state:
    st.session_state["durations"] = {}
if "zip_bytes" not in st.session_state:
    st.session_state["zip_bytes"] = None

# 為每個 video_id 儲存設定，若沒有就回傳 global_default
def get_effective_settings(video_id: str) -> dict:
    global_settings = st.session_state["global_settings"]
    video_settings = st.session_state["video_settings"].get(video_id, {})
    return {
        "fps": video_settings.get("fps", global_settings["fps"]),
        "width": video_settings.get("width", global_settings["width"]),
        "dither": video_settings.get("dither", global_settings["dither"]),
        "compress": video_settings.get("compress", global_settings["compress"]),
    }

def update_video_setting(video_id: str, key: str, value):
    if "video_settings" not in st.session_state:
        st.session_state["video_settings"] = {}
    if video_id not in st.session_state["video_settings"]:
        st.session_state["video_settings"][video_id] = {}
    st.session_state["video_settings"][video_id][key] = value

def generate_video_id(file) -> str:
    if not file:
        return ""
    raw = f"{file.name}:{file.size}".encode("utf-8", errors="ignore")
    return hashlib.md5(raw).hexdigest()

def get_preview_cache_key(video_id: str, fps: int, width: int, dither: str, compress: str) -> str:
    return f"prev_{video_id}_{fps}_{width}_{dither}_{compress}_5"

def get_final_cache_key(video_id: str, fps: int, width: int, dither: str, compress: str) -> str:
    return f"final_{video_id}_{fps}_{width}_{dither}_{compress}"

# ===================== 主畫面 =====================

st.title("GIF 轉檔工具（多檔上傳 / 單檔調整）")

# 顯示 ffmpeg / gifsicle 狀態
if not FFMPEG_AVAILABLE:
    st.error("偵測不到 ffmpeg，可用性受限。請在執行環境安裝 ffmpeg 後再重試。")
else:
    st.caption(f"已偵測到 ffmpeg 指令：`{FFMPEG_PATH}`")
if GIFSICLE_AVAILABLE:
    st.caption(f"已偵測到 gifsicle 指令：`{GIFSICLE_PATH}`")

col_left, col_right = st.columns([1.2, 1.8])

with col_left:
    st.markdown('<div class="left-card">', unsafe_allow_html=True)
    st.header("① 上傳影片 / GIF")

    uploaded_files = st.file_uploader(
        "上傳影片或 GIF 檔（可多選）",
        type=["mp4", "mov", "m4v", "gif"],
        accept_multiple_files=True,
        key="uploader",
    )

    if not uploaded_files:
        st.info("請先上傳至少一個檔案。")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.subheader("已上傳檔案")

        file_list_container = st.container()
        selected_id = st.session_state["selected_video_id"]

        with file_list_container:
            for f in uploaded_files:
                vid = generate_video_id(f)
                eff = get_effective_settings(vid)
                is_selected = (vid == selected_id)

                file_class = "selected" if is_selected else "unselected"
                file_label = f"{f.name}（FPS: {eff['fps']}, 寬度: {eff['width']}px, 畫質: {eff['dither']}, 壓縮: {eff['compress']}）"
                if st.button(
                    file_label,
                    key=f"btn_{vid}",
                    use_container_width=True,
                    help="點選後可在右側調整參數並預覽。",
                ):
                    st.session_state["selected_video_id"] = vid
                    selected_id = vid

        st.markdown('</div>', unsafe_allow_html=True)

with col_right:
    st.markdown('<div class="right-card">', unsafe_allow_html=True)
    st.header("② 單檔調整與預覽 / 下載")

    uploaded_files = st.session_state.get("uploader")
    if not uploaded_files:
        st.info("尚未上傳檔案。")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        if st.session_state["selected_video_id"] is None and uploaded_files:
            st.session_state["selected_video_id"] = generate_video_id(uploaded_files[0])

        selected_id = st.session_state["selected_video_id"]
        target_file = None
        for f in uploaded_files:
            if generate_video_id(f) == selected_id:
                target_file = f
                break

        if not target_file:
            st.info("選取的檔案不在目前清單中，請重新選取。")
        else:
            eff = get_effective_settings(selected_id)
            ext = Path(target_file.name).suffix.lower()
            is_gif = (ext == ".gif")

            # === 控制列（FPS / 寬度 / 畫質模式 / 壓縮程度）=== 置於同一列（兩種格式相同 UI）
            st.markdown('<div class="controls">', unsafe_allow_html=True)
            ctl1, ctl2, ctl3, ctl4 = st.columns([2, 2, 3, 3])

            with ctl1:
                st.markdown("FPS")
                current_fps = min(int(eff["fps"]), 10)  # 維持上限 10
                new_fps = st.slider("FPS", 1, 10, current_fps, key=f"fps_{selected_id}", label_visibility="collapsed")
                if new_fps != eff["fps"]:
                    update_video_setting(selected_id, "fps", int(new_fps))

            with ctl2:
                st.markdown("寬度（px）")
                w_val = st.number_input(
                    "寬度",
                    min_value=100,
                    max_value=1920,
                    value=int(eff["width"]),
                    step=2,
                    key=f"width_{selected_id}",
                    label_visibility="collapsed",
                )
                # 強制偶數
                if w_val % 2 != 0:
                    w_val = w_val - 1 if w_val > 100 else w_val + 1
                if int(w_val) != eff["width"]:
                    update_video_setting(selected_id, "width", int(w_val))

            # 畫質模式：三個中文選項，映射到 ffmpeg dither 值
            label_to_value = {"輕量模式": "none", "平衡模式": "bayer", "高品質模式": "sierra2_4a"}
            value_to_label = {
                "none": "輕量模式",
                "bayer": "平衡模式",
                "sierra2_4a": "高品質模式",
                "floyd_steinberg": "高品質模式",
                "sierra2": "高品質模式"
            }
            current_label = value_to_label.get(eff["dither"], "平衡模式")
            with ctl3:
                st.markdown("畫質模式")
                new_label = st.selectbox(
                    "畫質模式",
                    ["輕量模式", "平衡模式", "高品質模式"],
                    index=["輕量模式", "平衡模式", "高品質模式"].index(current_label),
                    key=f"dither_{selected_id}",
                    label_visibility="collapsed",
                )
                new_dither_value = label_to_value[new_label]
                if new_dither_value != eff["dither"]:
                    update_video_setting(selected_id, "dither", new_dither_value)

            with ctl4:
                st.markdown("壓縮程度")
                new_compress = st.selectbox(
                    "壓縮程度",
                    ["保守", "平衡", "強化", "激進"],
                    index=["保守", "平衡", "強化", "激進"].index(eff["compress"]),
                    key=f"compress_{selected_id}",
                    label_visibility="collapsed",
                )
                if new_compress != eff["compress"]:
                    update_video_setting(selected_id, "compress", new_compress)

            st.markdown('</div>', unsafe_allow_html=True)

            # ✅ 重新取得最新設定，確保以下參數使用的是最新的 fps / width / 畫質 / 壓縮
            eff = get_effective_settings(selected_id)

            # 準備參數與鍵值
            width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
            preview_key = get_preview_cache_key(selected_id, eff["fps"], width_even, eff["dither"], eff["compress"])
            final_key   = get_final_cache_key(selected_id,   eff["fps"], width_even, eff["dither"], eff["compress"])
            duration    = st.session_state["durations"].get(selected_id)

            # ===== 成品大小：以實際成品 bytes 為準（取代原本「預估大小」） =====
            size_placeholder = st.empty()
            if final_key in st.session_state["final_cache"]:
                size_placeholder.markdown(
                    f"**成品大小：{human_size(len(st.session_state['final_cache'][final_key]))}**"
                )
            else:
                size_placeholder.markdown("**成品大小：計算中…**")

            # 生成 5 秒預覽：兩種來源共用「以當前設定輸出 5 秒」的邏輯
            gif_bytes = None
            if preview_key in st.session_state["preview_cache"]:
                gif_bytes = st.session_state["preview_cache"][preview_key]
            else:
                input_bytes = target_file.getvalue()
                if is_gif:
                    ok, gif_bytes, err_msg = reencode_gif(
                        input_bytes,
                        fps=eff["fps"],
                        target_width=width_even,
                        dither=eff["dither"],
                        compress=eff["compress"],
                    )
                else:
                    ok, gif_bytes, err_msg = safe_convert(
                        input_bytes,
                        fps=eff["fps"],
                        target_width=width_even,
                        dither=eff["dither"],
                        compress=eff["compress"],
                        is_gif=False,
                    )

                if not ok or not gif_bytes:
                    st.error(f"預覽轉檔失敗：{err_msg}")
                    gif_bytes = None
                else:
                    st.session_state["preview_cache"][preview_key] = gif_bytes

            if gif_bytes:
                st.markdown("**5 秒預覽（實際輸出會是全長）**")
                st.image(gif_bytes, use_column_width=True)

            # ==== 產生完整 GIF ====
            st.markdown("---")
            st.subheader("輸出完整 GIF")

            if st.button("產生完整 GIF", key=f"make_full_{selected_id}"):
                with st.spinner("正在產生完整 GIF..."):
                    input_bytes = target_file.getvalue()
                    if is_gif:
                        ok, out_bytes, err_msg = reencode_gif(
                            input_bytes,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                        )
                    else:
                        ok, out_bytes, err_msg = safe_convert(
                            input_bytes,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                            is_gif=False,
                        )

                    if not ok or not out_bytes:
                        st.error(f"完整轉檔失敗：{err_msg}")
                    else:
                        st.session_state["final_cache"][final_key] = out_bytes
                        st.success("完整 GIF 轉檔完成！")
                        size_placeholder.markdown(
                            f"**成品大小：{human_size(len(out_bytes))}**"
                        )

            # === 下載單檔（置中）===
            if final_key in st.session_state["final_cache"]:
                st.markdown('<div class="center">', unsafe_allow_html=True)
                st.download_button(
                    "下載 GIF",
                    data=st.session_state["final_cache"][final_key],
                    file_name=f"{Path(target_file.name).stem}.gif",
                    mime="image/gif",
                    key=f"dl_single_{selected_id}",
                )
                st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

# ==================== 多檔批次輸出區 ====================

st.header("③ 批次輸出全部 GIF & 下載 ZIP")

if st.button("產生所有檔案的 GIF 並打包 ZIP", key="btn_make_all"):
    uploaded_files = st.session_state.get("uploader")
    if not uploaded_files:
        st.warning("目前沒有上傳任何檔案。")
    else:
        with st.spinner("準備所有 GIF 與 ZIP 封裝中..."):
            # 依各自設定補齊成品
            for f in uploaded_files:
                vid = generate_video_id(f)
                eff = get_effective_settings(vid)
                width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
                final_key = get_final_cache_key(vid, eff["fps"], width_even, eff["dither"], eff["compress"])

                if final_key not in st.session_state["final_cache"]:
                    data = f.getvalue()
                    ext = Path(f.name).suffix.lower()
                    is_gif = (ext == ".gif")

                    if is_gif:
                        ok, out_bytes, err_msg = reencode_gif(
                            data,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                        )
                    else:
                        ok, out_bytes, err_msg = safe_convert(
                            data,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                            is_gif=False,
                        )

                    if not ok or not out_bytes:
                        st.error(f"{f.name} 轉檔失敗：{err_msg}")
                    else:
                        st.session_state["final_cache"][final_key] = out_bytes

            # 打包 ZIP
            all_gifs = []
            for f in uploaded_files:
                vid = generate_video_id(f)
                eff = get_effective_settings(vid)
                width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
                final_key = get_final_cache_key(vid, eff["fps"], width_even, eff["dither"], eff["compress"])
                if final_key in st.session_state["final_cache"]:
                    all_gifs.append(
                        {"name": f"{Path(f.name).stem}.gif", "data": st.session_state["final_cache"][final_key]}
                    )

            if not all_gifs:
                st.warning("沒有任何成功轉檔的 GIF，可供打包。")
            else:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for item in all_gifs:
                        zf.writestr(item["name"], item["data"])
                st.session_state["zip_bytes"] = zip_buffer.getvalue()
                st.success("所有 GIF 已打包成 ZIP！請下方下載。")

if st.session_state.get("zip_bytes"):
    st.download_button(
        "下載所有 GIF 的 ZIP 檔",
        data=st.session_state["zip_bytes"],
        file_name="gifs_bundle.zip",
        mime="application/zip",
        key="dl_zip",
    )
