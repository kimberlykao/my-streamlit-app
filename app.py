import streamlit as st, shutil, subprocess
st.write("ffmpeg path:", shutil.which("ffmpeg"))
if shutil.which("ffmpeg"):
    v = subprocess.check_output(["ffmpeg","-version"]).decode().splitlines()[0]
    st.success(v)
else:
    st.error("ffmpeg not found")

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

def human_size(num_bytes: float) -> str:
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
        ok = (p.returncode == 0)
        if not ok:
            return False, (p.stderr or p.stdout or "").strip()
        return True, (p.stdout or "").strip()
    except Exception as e:
        return False, str(e)

# === 壓縮等級：顏色與 gifsicle optimize 等級對照 ===
_COMPRESS_PRESETS = {
    "保守":  {"colors": 256, "opt": 1},
    "平衡":  {"colors": 200, "opt": 2},
    "強化":  {"colors": 128, "opt": 3},
    "激進":  {"colors":  64, "opt": 3},
}

def gifsicle_optimize(gif_path: str, compress_level: str = "平衡") -> None:
    """依壓縮等級進行幀差最佳化；若系統沒有 gifsicle 则直接跳過。"""
    if not command_exists("gifsicle"):
        return
    preset = _COMPRESS_PRESETS.get(compress_level, _COMPRESS_PRESETS["平衡"])
    tmp_out = gif_path + ".opt.gif"
    ok, _ = run_cmd([
        "gifsicle",
        f"--colors={preset['colors']}",
        f"--optimize={preset['opt']}",
        "--batch", "--output", tmp_out, gif_path
    ])
    if ok and os.path.exists(tmp_out):
        try:
            os.replace(tmp_out, gif_path)
        except Exception:
            pass

def save_bytes_to_tmp(extension: str, data: bytes) -> str:
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
    tmp_file.write(data)
    tmp_file.close()
    return tmp_file.name

def get_media_duration_sec_from_bytes(data: bytes, suffix: str) -> float | None:
    """用 ffprobe 取得媒體秒數；suffix 例如 '.mp4'、'.gif'。失敗回傳 None。"""
    if not command_exists("ffprobe"):
        return None
    tmp_in = save_bytes_to_tmp(suffix, data)
    try:
        ok, out = run_cmd([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", tmp_in
        ])
        if ok and out.strip():
            try:
                return float(out.strip())
            except:
                pass
        # 再嘗試讀取串流的 duration
        ok2, out2 = run_cmd([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", tmp_in
        ])
        if ok2 and out2.strip():
            try:
                return float(out2.strip())
            except:
                pass
        return None
    finally:
        try: os.remove(tmp_in)
        except: pass

def get_media_dimensions_from_bytes(data: bytes, suffix: str) -> tuple[int, int] | None:
    """用 ffprobe 取得媒體寬高 (width, height)；suffix 例如 '.mp4'、'.gif'。失敗回傳 None。"""
    if not command_exists("ffprobe"):
        return None
    tmp_in = save_bytes_to_tmp(suffix, data)
    try:
        ok, out = run_cmd([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", tmp_in
        ])
        if ok and out.strip():
            try:
                parts = out.strip().split("x")
                if len(parts) == 2:
                    w = int(parts[0].strip()); h = int(parts[1].strip())
                    if w > 0 and h > 0:
                        return (w, h)
            except:
                pass
        return None
    finally:
        try: os.remove(tmp_in)
        except: pass

def safe_convert(
    src_mp4: str,
    out_gif: str,
    fps: int = 10,
    target_width: int = 800,
    dither: str = "bayer",
    trim_sec: int | None = None,
    compress: str = "平衡",
) -> tuple[bool, str]:
    """將 MP4/MOV 轉為 GIF（可選 5 秒預覽），並依壓縮等級優化。"""
    if not command_exists("ffmpeg"):
        return False, "系統未找到 ffmpeg，請先安裝後再試。"

    preset = _COMPRESS_PRESETS.get(compress, _COMPRESS_PRESETS["平衡"])
    palette_colors = preset["colors"]

    palette_path = out_gif + ".palette.png"
    vf_common = f"fps={fps},scale={target_width}:-2:flags=lanczos"

    # 先生成 palette（可剪 5 秒預覽）
    palette_cmd = ["ffmpeg", "-y", "-i", src_mp4, "-vf", f"{vf_common},palettegen=max_colors={palette_colors}", "-hide_banner"]
    if trim_sec and trim_sec > 0:
        palette_cmd = ["ffmpeg", "-y", "-t", str(trim_sec), "-i", src_mp4, "-vf", f"{vf_common},palettegen=max_colors={palette_colors}", "-hide_banner"]

    ok, err = run_cmd(palette_cmd + ["-frames:v", "99999", palette_path])
    if not ok:
        ok2, err2 = run_cmd(palette_cmd + [palette_path])
        if not ok2:
            return False, f"palette 生成失敗：{err2 or err}"

    # 映射 dither 名稱
    dither_final = {
        "none": "bayer",
        "bayer": "bayer",
        "sierra2_4a": "sierra2_4a",
        "floyd_steinberg": "floyd_steinberg",
        "sierra2": "sierra2",
    }.get(dither, "bayer")

    # 轉出 GIF（可剪 5 秒預覽）
    gif_cmd = [
        "ffmpeg", "-y", "-i", src_mp4, "-i", palette_path,
        "-lavfi", f"{vf_common}[x];[x][1:v]paletteuse=dither={dither_final}",
        "-gifflags", "+transdiff", "-an", "-hide_banner", out_gif
    ]
    if trim_sec and trim_sec > 0:
        gif_cmd = [
            "ffmpeg", "-y", "-t", str(trim_sec), "-i", src_mp4, "-i", palette_path,
            "-lavfi", f"{vf_common}[x];[x][1:v]paletteuse=dither={dither_final}",
            "-gifflags", "+transdiff", "-an", "-hide_banner", out_gif
        ]

    ok, err = run_cmd(gif_cmd)

    # 清除暫存 palette
    try:
        if os.path.exists(palette_path):
            os.remove(palette_path)
    except Exception:
        pass

    if not ok:
        return False, f"GIF 轉檔失敗：{err}"

    gifsicle_optimize(out_gif, compress_level=compress)
    return True, ""

def reencode_gif(
    src_gif: str,
    out_gif: str,
    fps: int = 10,
    target_width: int = 800,
    dither: str = "bayer",
    trim_sec: int | None = None,
    compress: str = "平衡",
) -> tuple[bool, str]:
    """將 GIF 重新編碼（可調 FPS / 寬度 / 畫質模式），再依壓縮等級最佳化。"""
    if not command_exists("ffmpeg"):
        return False, "系統未找到 ffmpeg，請先安裝後再試。"

    preset = _COMPRESS_PRESETS.get(compress, _COMPRESS_PRESETS["平衡"])
    palette_colors = preset["colors"]

    # 構造濾鏡鏈：有 fps 就加 fps=，有 width 就加 scale=
    vf_parts = []
    if fps and int(fps) > 0:
        vf_parts.append(f"fps={int(fps)}")
    if target_width and int(target_width) > 0:
        vf_parts.append(f"scale={int(target_width)}:-2:flags=lanczos")
    vf_common = ",".join(vf_parts) if vf_parts else "fps=10,scale=800:-2:flags=lanczos"

    palette_path = out_gif + ".palette.png"

    # 產生 palette
    palette_cmd = ["ffmpeg", "-y", "-i", src_gif, "-vf", f"{vf_common},palettegen=max_colors={palette_colors}", "-hide_banner"]
    if trim_sec and trim_sec > 0:
        palette_cmd = ["ffmpeg", "-y", "-t", str(trim_sec), "-i", src_gif, "-vf", f"{vf_common},palettegen=max_colors={palette_colors}", "-hide_banner"]

    ok, err = run_cmd(palette_cmd + ["-frames:v", "99999", palette_path])
    if not ok:
        ok2, err2 = run_cmd(palette_cmd + [palette_path])
        if not ok2:
            return False, f"palette 生成失敗：{err2 or err}"

    # dither 映射
    dither_final = {
        "none": "bayer",
        "bayer": "bayer",
        "sierra2_4a": "sierra2_4a",
        "floyd_steinberg": "floyd_steinberg",
        "sierra2": "sierra2",
    }.get(dither, "bayer")

    # 重新編碼 GIF
    gif_cmd = [
        "ffmpeg", "-y", "-i", src_gif, "-i", palette_path,
        "-lavfi", f"{vf_common}[x];[x][1:v]paletteuse=dither={dither_final}",
        "-gifflags", "+transdiff", "-an", "-hide_banner", out_gif
    ]
    if trim_sec and trim_sec > 0:
        gif_cmd = [
            "ffmpeg", "-y", "-t", str(trim_sec), "-i", src_gif, "-i", palette_path,
            "-lavfi", f"{vf_common}[x];[x][1:v]paletteuse=dither={dither_final}",
            "-gifflags", "+transdiff", "-an", "-hide_banner", out_gif
        ]

    ok, err = run_cmd(gif_cmd)

    try:
        if os.path.exists(palette_path):
            os.remove(palette_path)
    except Exception:
        pass

    if not ok:
        return False, f"GIF 重編碼失敗：{err}"

    gifsicle_optimize(out_gif, compress_level=compress)
    return True, ""

def generate_video_id(uploaded_file) -> str:
    return hashlib.md5(uploaded_file.name.encode()).hexdigest()[:12]

def get_preview_cache_key(video_id: str, fps: int, width: int, dither: str, compress: str) -> str:
    return f"preview_{video_id}_{fps}_{width}_{dither}_{compress}_5"

def get_final_cache_key(video_id: str, fps: int, width: int, dither: str, compress: str) -> str:
    return f"final_{video_id}_{fps}_{width}_{dither}_{compress}"

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
    if video_id not in st.session_state["video_settings"]:
        st.session_state["video_settings"][video_id] = {}
    st.session_state["video_settings"][video_id][key] = value
    if key in ["fps", "width", "dither", "compress"]:
        # 清除該影片快取，避免舊設定殘留
        preview_keys = [k for k in list(st.session_state["preview_cache"].keys()) if k.startswith(f"preview_{video_id}_")]
        for k in preview_keys:
            del st.session_state["preview_cache"][k]
        final_keys = [k for k in list(st.session_state["final_cache"].keys()) if k.startswith(f"final_{video_id}_")]
        for k in final_keys:
            del st.session_state["final_cache"][k]
        st.session_state["zip_all_bytes"] = None

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

# ======= 即時粗估：根據上一版 5 秒預覽做比例推估（保留給預估大小顯示）=======
_DITHER_FACTOR = {
    "none": 0.95,
    "bayer": 1.00,
    "sierra2_4a": 1.18,
    "floyd_steinberg": 1.08,
    "sierra2": 1.12,
}
def instant_estimate_bytes(prev_bytes: int, prev_fps: int, prev_width: int, prev_dither: str,
                           new_fps: int, new_width: int, new_dither: str) -> float:
    if prev_bytes is None or prev_bytes <= 0:
        return 0.0
    fps_ratio = max(new_fps, 1) / max(prev_fps, 1)
    width_ratio = max(new_width, 1) / max(prev_width, 1)
    dither_ratio = _DITHER_FACTOR.get(new_dither, 1.0) / _DITHER_FACTOR.get(prev_dither, 1.0)
    return float(prev_bytes) * fps_ratio * (width_ratio ** 2) * dither_ratio

# ===================== Streamlit 介面 =====================

st.set_page_config(page_title="GIF 轉檔器", layout="wide")
st.title("🎞 GIF 轉檔器")

# ====== 標題下方備註（20pt） ======
st.markdown(
    """
    <div style="font-size:20pt; font-weight:600; margin: -6px 0 10px 0;">
      Typeform 4MB / 嘖嘖 3MB
    </div>
    """,
    unsafe_allow_html=True
)

# 全域樣式：下載鈕紅底白字 200px；左欄檔名卡片樣式（radio：選取=灰底紅框）；控制列對齊
st.markdown(
    """
<style>
/* 下載按鈕：紅底白字 + 固定寬度 200px */
.stDownloadButton > button {
    background-color: #ff4b4b !important;
    color: #ffffff !important;
    border: none !important;
    font-weight: 700 !important;
    border-radius: 0.375rem !important;
    width: 200px !important;
}
.stDownloadButton > button:hover {
    background-color: #ff3333 !important;
    color: #ffffff !important;
}

/* 左欄清單容器 */
.file-list { display: flex; flex-direction: column; gap: 8px; }

/* radio 群組外框去掉多餘間距 */
.file-list .stRadio > div { gap: 8px !important; }

/* 每個 radio 選項 → 做成卡片 */
.file-list .stRadio [role="radio"] {
    width: 100%;
    text-align: left;
    border: 2px solid #ddd;
    background: #fff;
    color: #333;
    border-radius: 8px;
    padding: 10px 12px;
    transition: all .15s ease;
    outline: none !important;
}

/* hover 效果 */
.file-list .stRadio [role="radio"]:hover {
    border-color: #ff4b4b;
    box-shadow: 0 2px 8px rgba(255,75,75,0.15);
}

/* ✅ 被選取（aria-checked="true"）→ 灰底 + 紅框 */
.file-list .stRadio [role="radio"][aria-checked="true"] {
    background: #f0f0f0 !important;  /* 灰底 */
    border-color: #ff4b4b !important; /* 紅框 */
    border-width: 2px !important;
    box-shadow: none !important;
}

/* 被選取時的 hover 仍維持灰底紅框 */
.file-list .stRadio [role="radio"][aria-checked="true"]:hover {
    background: #f0f0f0 !important;
    border-color: #ff4b4b !重要;
    box-shadow: 0 2px 8px rgba(255,75,75,0.15) !important;
}

/* 控制列：讓四種元件視覺高度更接近（微調上下間距） */
.controls .stSlider, .controls .stNumberInput, .controls .stSelectbox {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}
.controls .stMarkdown { margin-bottom: 4px !important; }

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
if "zip_all_bytes" not in st.session_state:
    st.session_state["zip_all_bytes"] = None
if "durations" not in st.session_state:
    st.session_state["durations"] = {}  # video_id -> seconds
if "last_preview_meta" not in st.session_state:
    st.session_state["last_preview_meta"] = {}  # video_id -> dict(bytes, fps, width, dither)
if "src_dims" not in st.session_state:
    st.session_state["src_dims"] = {}  # video_id -> (w,h)

# ---- 佈局：左 30% / 右 70% ----
left, right = st.columns([3, 7], gap="large")

# =============== 左側（30%） ===============
with left:
    st.markdown("### MP4/MOV/GIF 上傳")
    uploaded_files = st.file_uploader(
        "上傳 MP4/MOV/GIF（可多選）",
        type=["mp4", "mov", "gif"],
        accept_multiple_files=True,
        key="uploader_left_only",
    )

    st.markdown("### 影片清單")
    if uploaded_files:
        # 初始化 per-file 設定、時長與原始尺寸（MP4/MOV/GIF 都嘗試抓）
        for f in uploaded_files:
            vid = generate_video_id(f)
            if vid not in st.session_state["video_settings"]:
                st.session_state["video_settings"][vid] = {}
            ext = Path(f.name).suffix.lower()
            if vid not in st.session_state["durations"]:
                dur = get_media_duration_sec_from_bytes(f.getvalue(), suffix=ext if ext in (".mp4", ".mov", ".gif") else ".mp4")
                if dur and dur > 0:
                    st.session_state["durations"][vid] = dur
            if vid not in st.session_state["src_dims"]:
                dims = get_media_dimensions_from_bytes(f.getvalue(), suffix=ext if ext in (".mp4", ".mov", ".gif") else ".mp4")
                if dims:
                    st.session_state["src_dims"][vid] = dims

        # 準備 radio 選項（使用 video_id 當值，檔名當顯示文字）
        options = [(generate_video_id(f), f.name) for f in uploaded_files]
        option_ids = [vid for vid, _ in options]
        id_to_name = {vid: name for vid, name in options}

        # 若尚未選取，預設選第一支
        if not st.session_state["selected_video_id"]:
            st.session_state["selected_video_id"] = option_ids[0]

        # 目前選取 index
        current_id = st.session_state["selected_video_id"]
        if current_id not in option_ids:
            current_id = option_ids[0]
            st.session_state["selected_video_id"] = current_id
        current_index = option_ids.index(current_id)

        # 用 radio 呈現清單（卡片化）
        st.markdown('<div class="file-list">', unsafe_allow_html=True)
        selected_id = st.radio(
            "影片清單",
            options=option_ids,
            index=current_index,
            format_func=lambda x: f"📄 {id_to_name.get(x, x)}",
            label_visibility="collapsed",
            key="radio_select_video",
        )
        st.markdown('</div>', unsafe_allow_html=True)

        # 寫回選取狀態
        if selected_id != st.session_state["selected_video_id"]:
            st.session_state["selected_video_id"] = selected_id
            st.rerun()

        # 顯示原始尺寸（任一格式）
        w_h = st.session_state["src_dims"].get(selected_id)
        if w_h:
            st.markdown(
                f'<div class="dim-note">原始尺寸：{w_h[0]} × {w_h[1]} px</div>',
                unsafe_allow_html=True
            )

        # 一鍵下載（若 zip 快取不存在就先準備）
        if not st.session_state["zip_all_bytes"]:
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

                        if ext == ".gif":
                            # ✅ GIF：重新編碼
                            tmp_in = save_bytes_to_tmp(".gif", data)
                            out_final = tmp_in.replace(".gif", "_final.gif")
                            ok, err = reencode_gif(
                                src_gif=tmp_in,
                                out_gif=out_final,
                                fps=eff["fps"],
                                target_width=width_even,
                                dither=eff["dither"],
                                trim_sec=None,
                                compress=eff["compress"],
                            )
                            if ok:
                                with open(out_final, "rb") as fo:
                                    st.session_state["final_cache"][final_key] = fo.read()
                            else:
                                st.error(f"{f.name} 轉檔失敗：{err}")
                            try: os.remove(tmp_in)
                            except: pass
                            try: os.remove(out_final)
                            except: pass
                        else:
                            # ✅ MP4/MOV：沿用原本流程
                            tmp_in = save_bytes_to_tmp(".mp4", data)
                            out_final = tmp_in.replace(".mp4", "_final.gif")
                            ok, err = safe_convert(
                                src_mp4=tmp_in,
                                out_gif=out_final,
                                fps=eff["fps"],
                                target_width=width_even,
                                dither=eff["dither"],
                                trim_sec=None,
                                compress=eff["compress"],
                            )
                            if ok:
                                with open(out_final, "rb") as fo:
                                    st.session_state["final_cache"][final_key] = fo.read()
                            else:
                                st.error(f"{f.name} 轉檔失敗：{err}")
                            try: os.remove(tmp_in)
                            except: pass
                            try: os.remove(out_final)
                            except: pass

                # 打包 ZIP
                all_gifs = []
                for f in uploaded_files:
                    vid = generate_video_id(f)
                    eff = get_effective_settings(vid)
                    width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
                    final_key = get_final_cache_key(vid, eff["fps"], width_even, eff["dither"], eff["compress"])
                    if final_key in st.session_state["final_cache"]:
                        all_gifs.append(
                            {"name": f"{Path(f.name).stem}.gif",
                             "data": st.session_state["final_cache"][final_key]}
                        )
                if all_gifs:
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for item in all_gifs:
                            zf.writestr(item["name"], item["data"])
                    buf.seek(0)
                    st.session_state["zip_all_bytes"] = buf.read()
                else:
                    st.session_state["zip_all_bytes"] = None

        if st.session_state["zip_all_bytes"]:
            st.download_button(
                "📦 一鍵下載所有 GIF（ZIP）",
                data=st.session_state["zip_all_bytes"],
                file_name="all_gifs.zip",
                mime="application/zip",
                key="download_zip_all",
            )
        else:
            st.info("正在準備 ZIP 或沒有可打包的 GIF。")
    else:
        st.info("尚未上傳任何檔案。")

# =============== 右側（70%） ===============
with right:
    st.markdown("### GIF預覽與設定")

    if not st.session_state.get("selected_video_id") or not uploaded_files:
        st.info("請先在左側上傳並選取一支檔案。")
    else:
        # 找被選取的檔案
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
                if is_gif:
                    with st.spinner("生成 5 秒 GIF 預覽中..."):
                        data = target_file.getvalue()
                        tmp_in = save_bytes_to_tmp(".gif", data)
                        out_preview = tmp_in.replace(".gif", "_preview.gif")
                        ok, err = reencode_gif(
                            src_gif=tmp_in,
                            out_gif=out_preview,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            trim_sec=5,
                            compress=eff["compress"],
                        )
                        if ok:
                            with open(out_preview, "rb") as f:
                                gif_bytes = f.read()
                            st.session_state["preview_cache"][preview_key] = gif_bytes
                            st.session_state["last_preview_meta"][selected_id] = {
                                "bytes": len(gif_bytes),
                                "fps": eff["fps"],
                                "width": width_even,
                                "dither": eff["dither"],
                            }
                        else:
                            st.info(f"⚠️ 無法生成 GIF 預覽（{err}）。")
                        try: os.remove(tmp_in)
                        except: pass
                        try: os.remove(out_preview)
                        except: pass
                else:
                    with st.spinner("生成 5 秒 GIF 預覽中..."):
                        data = target_file.getvalue()
                        tmp_in = save_bytes_to_tmp(".mp4", data)
                        out_preview = tmp_in.replace(".mp4", "_preview.gif")
                        ok, err = safe_convert(
                            src_mp4=tmp_in,
                            out_gif=out_preview,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            trim_sec=5,
                            compress=eff["compress"],
                        )
                        if ok:
                            with open(out_preview, "rb") as f:
                                gif_bytes = f.read()
                            st.session_state["preview_cache"][preview_key] = gif_bytes
                            st.session_state["last_preview_meta"][selected_id] = {
                                "bytes": len(gif_bytes),
                                "fps": eff["fps"],
                                "width": width_even,
                                "dither": eff["dither"],
                            }
                        else:
                            gif_bytes = None
                            st.info("⚠️ 無法生成 GIF 預覽（可能未安裝 ffmpeg 或轉檔失敗）。")
                        try: os.remove(tmp_in)
                        except: pass
                        try: os.remove(out_preview)
                        except: pass

            # 顯示 GIF 圖片
            if gif_bytes:
                gif_b64 = b64(gif_bytes)
                st.markdown(
                    f"""
<div style="width:100%; display:flex; justify-content:center; margin: 8px 0 4px 0;">
  <img alt="GIF 預覽" style="width:100%; max-width:900px; height:auto; object-fit:contain; border-radius:6px; background:#111;" src="data:image/gif;base64,{gif_b64}" />
</div>
""",
                    unsafe_allow_html=True,
                )

            # === 準備成品（依目前設定）===
            if final_key not in st.session_state["final_cache"]:
                if is_gif:
                    with st.spinner("準備最終 GIF（依目前設定）..."):
                        data = target_file.getvalue()
                        tmp_in = save_bytes_to_tmp(".gif", data)
                        out_final = tmp_in.replace(".gif", "_final.gif")
                        ok, err = reencode_gif(
                            src_gif=tmp_in,
                            out_gif=out_final,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            trim_sec=None,
                            compress=eff["compress"],
                        )
                        if ok:
                            with open(out_final, "rb") as f:
                                final_bytes = f.read()
                            st.session_state["final_cache"][final_key] = final_bytes
                            st.session_state["zip_all_bytes"] = None
                            # ✅ 成品完成後即刻更新大小顯示
                            size_placeholder.markdown(f"**成品大小：{human_size(len(final_bytes))}**")
                        else:
                            st.error(f"{target_file.name} 成品轉檔失敗：{err}")
                        try: os.remove(tmp_in)
                        except: pass
                        try: os.remove(out_final)
                        except: pass
                else:
                    with st.spinner("準備最終 GIF（依目前設定）..."):
                        data = target_file.getvalue()
                        tmp_in = save_bytes_to_tmp(".mp4", data)
                        out_final = tmp_in.replace(".mp4", "_final.gif")
                        ok, err = safe_convert(
                            src_mp4=tmp_in,
                            out_gif=out_final,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            trim_sec=None,
                            compress=eff["compress"],
                        )
                        if ok:
                            with open(out_final, "rb") as f:
                                final_bytes = f.read()
                            st.session_state["final_cache"][final_key] = final_bytes
                            st.session_state["zip_all_bytes"] = None
                            # ✅ 成品完成後即刻更新大小顯示
                            size_placeholder.markdown(f"**成品大小：{human_size(len(final_bytes))}**")
                        else:
                            st.error(f"{target_file.name} 成品轉檔失敗：{err}")
                        try: os.remove(tmp_in)
                        except: pass
                        try: os.remove(out_final)
                        except: pass

            # === 下載單檔（置中 + 200px 寬）===
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
