import os
import string

from PIL import ImageFont

from .utils import _is_vertical_ratio, _get_render_dims


def build_ass_file(
    data_segments,
    start_clip,
    end_clip,
    ass_file_name,
    ratio,
    cfg,
    typography_plan=None,
    use_advanced=True,
    get_x_func=None,
    source_dim=None,
):
    """
    Build and write an Advanced SubStation Alpha (ASS) subtitle file for a video clip.

    Args:
        data_segments (list): A list of dictionaries containing transcript segments and their timing.
        start_clip (float): The starting timestamp of the clip in the original video (in seconds).
        end_clip (float): The ending timestamp of the clip in the original video (in seconds).
        ass_file_name (str): The destination file path to save the generated ASS file.
        ratio (str): The target aspect ratio ('9:16' or '16:9').
        cfg: Runtime configuration object specifying styling, fonts, and render settings.
        typography_plan (list, optional): A list of dictionaries specifying emphasis and animation for specific words. Defaults to None.
        use_advanced (bool, optional): Whether to use advanced positioning and animations. Defaults to True.
        get_x_func (callable, optional): A function taking a timestamp and returning the X-coordinate for dynamic tracking.
        source_dim (tuple, optional): Source video dimension tuple `(width, height)`.

    Returns:
        None

    Side Effects:
        Writes formatting and subtitle event data to the local file specified by `ass_file_name`.

    Raises:
        FileNotFoundError: If advanced mode is used and the configured font files are missing from the font directory.
    """
    if typography_plan is None:
        typography_plan = []

    typo_dict = {}
    for plan in typography_plan:
        clean_word = plan.get("word", "").lower().strip(string.punctuation)
        typo_dict[clean_word] = plan

    use_advanced_text = cfg.use_advanced_text and use_advanced
    use_karaoke = cfg.use_karaoke_effect

    outline_val = 3 if use_karaoke else 0.2
    shadow_val = 2.5 if use_karaoke else 0.2

    font_presets = cfg.font_presets
    style = cfg.active_font_style
    font_dir = cfg.font_dir

    primary_font_dict = font_presets[style]["main"]
    accent_font_dict = font_presets[style]["accent"]

    primary_font = primary_font_dict["name"]
    accent_font = accent_font_dict["name"]

    accent_scale_base = (
        cfg.accent_word_scale_916 if _is_vertical_ratio(ratio) else cfg.accent_word_scale_169
    )
    accent_color = cfg.accent_word_color

    def get_scale_value(level):
        if level == 3:
            return accent_scale_base
        elif level == 2:
            return int((accent_scale_base + 100) / 2)
        else:
            return 110

    def fmt_time(d):
        return f"{int(d // 3600)}:{int((d % 3600) // 60):02d}:{int(d % 60):02d}.{int((d - int(d)) * 100):02d}"

    play_res_x, play_res_y = _get_render_dims(cfg, ratio, source_h=source_dim[1] if source_dim else 1080)
    
    # Calculate scale relative to standard 1080p vertical (1920 height)
    # This ensures typography looks consistent across different render resolutions
    scale_factor = play_res_y / (1920 if _is_vertical_ratio(ratio) else 1080)
    if ratio == "split":
        align = 5
        margin_v = 0
    else:
        align = cfg.ass_align_916 if _is_vertical_ratio(ratio) else cfg.ass_align_169
        margin_v = int((cfg.ass_margin_916 if _is_vertical_ratio(ratio) else cfg.ass_margin_169) * scale_factor)
    font_sz = int((cfg.ass_font_916 if _is_vertical_ratio(ratio) else cfg.ass_font_169) * scale_factor)
    margin_lr = int((60 if _is_vertical_ratio(ratio) else 40) * scale_factor)

    header = (
        f"[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        f"WrapStyle: 1\n"
        f"ScriptType: v4.00+\n"
        f"ScaledBorderAndShadow: yes\n\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{primary_font},{font_sz},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{outline_val},{shadow_val},{align},{margin_lr},{margin_lr},{margin_v},1\n\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def font_exists_in_dir(file_name, min_valid_size=1000):
        path = os.path.join(font_dir, file_name)
        return os.path.exists(path) and os.path.getsize(path) > min_valid_size

    if not use_advanced_text:
        with open(ass_file_name, "w", encoding="utf-8") as f:
            f.write(header)
            for seg in data_segments:
                seg_s = max(0, seg["start"] - start_clip)
                seg_e = min(end_clip - start_clip, seg["end"] - start_clip)
                if seg_s >= seg_e:
                    continue

                for i, w in enumerate(seg["words"]):
                    w_s = max(0, w["start"] - start_clip)
                    if i < len(seg["words"]) - 1:
                        w_e = min(
                            end_clip - start_clip,
                            seg["words"][i + 1]["start"] - start_clip,
                        )
                    else:
                        w_e = min(end_clip - start_clip, w["end"] - start_clip)

                    if w_s < w_e:
                        text_parts = []
                        for j, x in enumerate(seg["words"]):
                            if use_karaoke:
                                if j == i:
                                    text_parts.append(
                                        f"{{\\c&H00FFFF&}}{x['word']}{{\\c&HFFFFFF&}}"
                                    )
                                else:
                                    text_parts.append(x["word"])
                            else:
                                if j <= i:
                                    text_parts.append(x["word"])
                                else:
                                    text_parts.append(
                                        f"{{\\alpha&HFF&}}{x['word']}{{\\alpha&H00&}}"
                                    )

                        f.write(
                            f"Dialogue: 0,{fmt_time(w_s)},{fmt_time(w_e)},Default,,0,0,0,,{' '.join(text_parts)}\n"
                        )
        return

    # Advanced typography mode
    font_cache = {}

    def get_cached_font(is_accent, scale_val):
        key = f"{is_accent}_{scale_val}"
        if key not in font_cache:
            f_info = accent_font_dict if is_accent else primary_font_dict
            f_file = f_info["file"]
            f_path = os.path.join(font_dir, f_file)

            if not font_exists_in_dir(f_file):
                raise FileNotFoundError(f"Font not found: {f_path}")

            font_cache[key] = ImageFont.truetype(
                f_path,
                int(font_sz * (scale_val / 100.0)),
            )
        return font_cache[key]

    def build_font_tag(font_info):
        name = str(font_info["name"]).replace("{", "").replace("}", "").strip()
        bold = 1 if int(font_info.get("bold", 0)) else 0
        return f"\\fn{name}\\b{bold}"

    max_line_width = play_res_x - (margin_lr * 2)
    space_width = font_sz * 0.25
    TIGHTNESS = 0.95

    with open(ass_file_name, "w", encoding="utf-8") as f:
        f.write(header)

        for seg in data_segments:
            seg_s = max(0, seg["start"] - start_clip)
            seg_e = min(end_clip - start_clip, seg["end"] - start_clip)
            if seg_s >= seg_e:
                continue

            lines = []
            current_line = []
            current_w = 0
            max_line_h = 0

            for w_dict in seg["words"]:
                word_clean = w_dict["word"].lower().strip(string.punctuation)
                plan = typo_dict.get(word_clean)

                if plan:
                    w_style = plan.get("style", "accent")
                    w_scale = get_scale_value(plan.get("scale_level", 2))
                    is_accent = w_style == "accent"

                    pil_font = get_cached_font(is_accent, w_scale)
                    raw_w = (
                        pil_font.getlength(w_dict["word"])
                        if hasattr(pil_font, "getlength")
                        else len(w_dict["word"]) * 20
                    )
                    w_len = raw_w * TIGHTNESS
                    h_len = font_sz * (w_scale / 100.0)
                else:
                    w_scale = 100
                    pil_font = get_cached_font(False, w_scale)
                    raw_w = (
                        pil_font.getlength(w_dict["word"])
                        if hasattr(pil_font, "getlength")
                        else len(w_dict["word"]) * 15
                    )
                    w_len = raw_w * TIGHTNESS
                    h_len = font_sz

                if current_line and (current_w + space_width + w_len > max_line_width):
                    lines.append(
                        {
                            "words": current_line,
                            "width": current_w,
                            "height": max_line_h,
                        }
                    )
                    current_line = []
                    current_w = 0
                    max_line_h = 0

                x_offset = current_w if not current_line else current_w + space_width
                current_line.append(
                    {
                        "text": w_dict["word"],
                        "plan": plan,
                        "w": w_len,
                        "h": h_len,
                        "x_offset": x_offset,
                        "start": max(0, w_dict["start"] - start_clip),
                        "end": min(end_clip - start_clip, w_dict["end"] - start_clip),
                    }
                )

                current_w = x_offset + w_len
                max_line_h = max(max_line_h, h_len)

            if current_line:
                lines.append(
                    {"words": current_line, "width": current_w, "height": max_line_h}
                )

            line_spacing = 15
            total_stack_h = (
                sum(l["height"] for l in lines) + (len(lines) - 1) * line_spacing
            )
            if ratio == "split":
                current_y = (play_res_y - total_stack_h) / 2
            else:
                current_y = play_res_y - margin_v - total_stack_h

            for line in lines:
                start_x = (play_res_x - line["width"]) / 2
                
                if get_x_func and cfg.dev_mode and source_dim:
                    sw, sh = source_dim
                    # Reference time: midpoint of the current segment/line
                    t_ref = line["words"][0]["start"] + start_clip
                    center_x_src = get_x_func(t_ref)
                    # Target center in PlayResX (1920)
                    target_center_x = center_x_src * (play_res_x / sw)
                    start_x = target_center_x - (line["width"] / 2)

                line_y = current_y + line["height"]

                for w_data in line["words"]:
                    word_x = start_x + w_data["x_offset"] + (w_data["w"] / 2)
                    w_appear_ms = int((w_data["start"] - seg_s) * 1000)
                    w_end_ms = int((w_data["end"] - seg_s) * 1000)

                    if w_data["plan"]:
                        w_style = w_data["plan"].get("style", "accent")
                        w_anim = w_data["plan"].get("animation", "bounce_pop")
                        target_scale = get_scale_value(
                            w_data["plan"].get("scale_level", 2)
                        )
                        font_info = (
                            accent_font_dict if w_style == "accent" else primary_font_dict
                        )
                        f_tag = build_font_tag(font_info)
                        c_tag = f"\\c{accent_color}"
                    else:
                        w_anim = "none"
                        target_scale = 100
                        f_tag = build_font_tag(primary_font_dict)
                        c_tag = "\\c&HFFFFFF&"

                    t_start = w_appear_ms
                    t_pop = w_appear_ms + 80
                    t_settle = w_appear_ms + 150

                    if use_karaoke:
                        pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                        c_tag = "\\c&HFFFFFF&"
                        anim_tag = f"\\fscx{target_scale}\\fscy{target_scale}\\t({t_start},{t_start},\\c&H00FFFF&)\\t({w_end_ms},{w_end_ms},\\c&HFFFFFF&)"
                    else:
                        if w_anim == "stagger_up":
                            y_start = int(line_y + 30)
                            pos_tag = f"\\move({int(word_x)},{y_start},{int(word_x)},{int(line_y)},{t_start},{t_settle})"
                            anim_tag = f"\\alpha&HFF&\\fscx{target_scale}\\fscy{target_scale}\\t({t_start},{t_start},\\alpha&H00&)"
                        elif w_anim == "bounce_pop":
                            init_scale = int(target_scale * 0.7)
                            overshoot = int(target_scale * 1.15)
                            pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                            anim_tag = (
                                f"\\alpha&HFF&\\fscx{init_scale}\\fscy{init_scale}"
                                f"\\t({t_start},{t_start},\\alpha&H00&)"
                                f"\\t({t_start},{t_pop},\\fscx{overshoot}\\fscy{overshoot})"
                                f"\\t({t_pop},{t_settle},\\fscx{target_scale}\\fscy{target_scale})"
                            )
                        else:
                            pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                            anim_tag = f"\\alpha&HFF&\\fscx{target_scale}\\fscy{target_scale}\\t({t_start},{t_start},\\alpha&H00&)"

                    event_text = (
                        f"{{\\an2{pos_tag}{f_tag}{c_tag}{anim_tag}}}{w_data['text']}"
                    )
                    f.write(
                        f"Dialogue: 0,{fmt_time(seg_s)},{fmt_time(seg_e)},Default,,0,0,0,,{event_text}\n"
                    )

                current_y += line["height"] + line_spacing


