"""
clipping.studio.subtitles — Burned-in captions (ASS).

Two looks share this module:
- the default kinetic style: each word placed individually in a heavy font with
  a thick outline; the word being spoken pops and lights up in the accent
  colour, and the AI's keywords stay larger and in the accent colour;
- ``--simple-captions``: one line per word group with a karaoke colour change.

Both can be uppercased with ``--caption-case upper``. An optional headline
(``title_overlay``) is boxed at the top of the frame for the opening seconds.
"""

import os
import string

from PIL import ImageFont

from .utils import _get_render_dims, _is_vertical_ratio

WHITE = "&HFFFFFF&"
POP_SCALE = 1.08  # the spoken word briefly grows by this factor
LINE_SPACING = 15
TIGHTNESS = 1.0  # measured widths match libass once converted (see _libass_em_ratio)

# A caption stays on screen through a pause this short, until the next group
# starts; each group used to vanish at its last word and blink between groups.
CAPTION_HOLD_GAP = 0.6

_EM_RATIO_CACHE: dict = {}


def _held_end(segments, index):
    """When caption group *index* should disappear (bridging short pauses)."""
    seg = segments[index]
    if index + 1 < len(segments):
        gap = segments[index + 1]["start"] - seg["end"]
        if 0 <= gap <= CAPTION_HOLD_GAP:
            return segments[index + 1]["start"]
    return seg["end"]


def _libass_em_ratio(font_path):
    """
    Font-size conversion between libass and Pillow for one font file.

    libass (like VSFilter) makes the font's Windows ascent+descent equal the ASS
    font size, while Pillow sizes the em square. Measuring words with Pillow at
    the raw ASS size overestimated every width by ~20%, so the per-word layout
    left wide gaps between words.
    """
    if font_path in _EM_RATIO_CACHE:
        return _EM_RATIO_CACHE[font_path]

    ratio = None
    try:
        import struct

        with open(font_path, "rb") as f:
            data = f.read()
        num_tables = struct.unpack(">H", data[4:6])[0]
        tables = {}
        for i in range(num_tables):
            tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            tables[tag] = offset
        units_per_em = struct.unpack(">H", data[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        win_ascent, win_descent = struct.unpack(">HH", data[tables[b"OS/2"] + 74: tables[b"OS/2"] + 78])
        if win_ascent + win_descent > 0:
            ratio = units_per_em / (win_ascent + win_descent)
    except Exception:
        ratio = None

    if ratio is None:
        probe = ImageFont.truetype(font_path, 1000)
        ascent, descent = probe.getmetrics()
        ratio = 1000.0 / max(1, ascent + descent)

    _EM_RATIO_CACHE[font_path] = ratio
    return ratio


def _fmt_time(seconds):
    centis = int(round(max(0.0, seconds) * 100))
    return f"{centis // 360000}:{(centis // 6000) % 60:02d}:{(centis // 100) % 60:02d}.{centis % 100:02d}"


def build_ass_file(
    data_segments,
    start_clip,
    end_clip,
    ass_file_name,
    ratio,
    cfg,
    typography_plan=None,
    use_advanced=True,
    source_dim=None,
    title_overlay=None,
):
    """
    Build and write an Advanced SubStation Alpha (ASS) subtitle file for a clip.

    Args:
        data_segments (list): Transcript chunks, each with timed ``words``.
        start_clip (float): Clip start in the source video (seconds).
        end_clip (float): Clip end in the source video (seconds).
        ass_file_name (str): Destination path.
        ratio (str): Target aspect ratio.
        cfg: Runtime configuration (fonts, colours, caption style).
        typography_plan (list, optional): Keyword emphasis chosen by the AI.
        use_advanced (bool, optional): Allow the kinetic style for this file.
        source_dim (tuple, optional): Source ``(width, height)``, for the render size.
        title_overlay (dict, optional): ``{"text": str, "duration": float}`` headline.

    Raises:
        FileNotFoundError: The kinetic style is used and a configured font file is missing.
    """
    typo_dict = {
        str(plan.get("word", "")).lower().strip(string.punctuation): plan
        for plan in (typography_plan or [])
    }

    use_advanced_text = getattr(cfg, "use_advanced_text", True) and use_advanced
    use_karaoke = cfg.use_karaoke_effect
    upper = str(getattr(cfg, "caption_case", "normal")).lower() == "upper"

    def show(word):
        text = str(word).replace("{", "(").replace("}", ")").replace("\\", "")
        # Trailing commas and full stops clutter short captions; ? and ! carry meaning.
        if len(text) > 1 and text.endswith((",", ".")) and not text.endswith(".."):
            text = text[:-1]
        return text.upper() if upper else text

    font_dir = cfg.font_dir
    preset = cfg.font_presets[cfg.active_font_style]
    primary_font_dict, accent_font_dict = preset["main"], preset["accent"]
    primary_font = primary_font_dict["name"]

    vertical = _is_vertical_ratio(ratio)
    accent_scale_base = cfg.accent_word_scale_916 if vertical else cfg.accent_word_scale_169
    accent_color = cfg.accent_word_color

    def get_scale_value(level):
        if level == 3:
            return accent_scale_base
        if level == 2:
            return int((accent_scale_base + 100) / 2)
        return 110

    play_res_x, play_res_y = _get_render_dims(
        cfg, ratio, source_h=source_dim[1] if source_dim else 1080
    )
    # Sizes are designed for 1080x1920 (vertical) / 1920x1080 and scaled from there.
    scale_factor = play_res_y / (1920 if vertical else 1080)
    align = cfg.ass_align_916 if vertical else cfg.ass_align_169
    margin_v = int((cfg.ass_margin_916 if vertical else cfg.ass_margin_169) * scale_factor)
    base_font = getattr(cfg, "caption_font_size", None) or (
        cfg.ass_font_916 if vertical else cfg.ass_font_169
    )
    font_sz = int(base_font * scale_factor)
    margin_lr = int((60 if vertical else 40) * scale_factor)
    outline_val = max(2, round(5 * scale_factor))
    shadow_val = max(1, round(2 * scale_factor))

    # Title overlay: a semi-opaque box (BorderStyle 3) in the upper area, clear
    # of the platform UI at the very top and of the captions lower down.
    title_sz = int(font_sz * 0.78)
    title_margin_v = int(play_res_y * (0.14 if vertical else 0.07))
    title_margin_lr = int((90 if vertical else 160) * scale_factor)
    title_box_pad = max(8, int(18 * scale_factor))
    title_bold = 0 if int(primary_font_dict.get("bold", 0)) else -1

    header = (
        f"[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        f"WrapStyle: 1\n"
        f"ScriptType: v4.00+\n"
        f"ScaledBorderAndShadow: yes\n\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{primary_font},{font_sz},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{outline_val},{shadow_val},{align},{margin_lr},{margin_lr},{margin_v},1\n"
        f"Style: HookTitle,{primary_font},{title_sz},&H00FFFFFF,&H33000000,&H00000000,{title_bold},0,0,0,100,100,0,0,3,{title_box_pad},0,8,{title_margin_lr},{title_margin_lr},{title_margin_v},1\n\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    clip_len = max(0.0, end_clip - start_clip)
    if title_overlay and title_overlay.get("text") and clip_len > 0:
        overlay_text = (
            str(title_overlay["text"]).replace("\\", "").replace("{", "(").replace("}", ")")
        )
        overlay_end = min(float(title_overlay.get("duration", 4.0)), clip_len)
        # \q0 re-enables smart wrapping so a long headline breaks into two balanced lines.
        header += (
            f"Dialogue: 1,{_fmt_time(0)},{_fmt_time(overlay_end)},HookTitle,,0,0,0,,"
            f"{{\\q0\\fad(120,250)}}{overlay_text}\n"
        )

    if not use_advanced_text:
        _write_simple(ass_file_name, header, data_segments, start_clip, clip_len,
                      use_karaoke, accent_color, show)
        return

    # ---- kinetic style ----------------------------------------------------------
    font_cache = {}

    def get_cached_font(is_accent, scale_val):
        key = (is_accent, scale_val)
        if key not in font_cache:
            f_info = accent_font_dict if is_accent else primary_font_dict
            f_path = os.path.join(font_dir, f_info["file"])
            if not (os.path.exists(f_path) and os.path.getsize(f_path) > 1000):
                raise FileNotFoundError(f"Font not found: {f_path}")
            size = font_sz * (scale_val / 100.0) * _libass_em_ratio(f_path)
            font_cache[key] = ImageFont.truetype(f_path, max(1, int(round(size))))
        return font_cache[key]

    def build_font_tag(font_info):
        name = str(font_info["name"]).replace("{", "").replace("}", "").strip()
        bold = 1 if int(font_info.get("bold", 0)) else 0
        return f"\\fn{name}\\b{bold}"

    def uses_accent_font(plan):
        # With the spoken-word highlight, keywords stay in the heavy main font and
        # stand out by size and colour; switching to a lighter accent font (e.g.
        # Montserrat Medium) looked like a glitch in the middle of a caption.
        return bool(plan) and plan.get("style", "accent") == "accent" and not use_karaoke

    max_line_width = play_res_x - (margin_lr * 2)
    space_font = get_cached_font(False, 100)
    # A real space plus both neighbours' outlines, so heavy outlined words don't touch.
    space_width = (
        space_font.getlength(" ") if hasattr(space_font, "getlength") else font_sz * 0.2
    ) + 2 * outline_val

    with open(ass_file_name, "w", encoding="utf-8") as f:
        f.write(header)

        for seg_index, seg in enumerate(data_segments):
            seg_s = max(0, seg["start"] - start_clip)
            seg_e = min(clip_len, _held_end(data_segments, seg_index) - start_clip)
            if seg_s >= seg_e:
                continue

            # Lay the words out into lines that fit the frame width.
            lines = []
            current_line, current_w, max_line_h = [], 0, 0
            for w_dict in seg["words"]:
                plan = typo_dict.get(w_dict["word"].lower().strip(string.punctuation))
                text = show(w_dict["word"])
                if plan:
                    w_scale = get_scale_value(plan.get("scale_level", 2))
                    pil_font = get_cached_font(uses_accent_font(plan), w_scale)
                else:
                    w_scale = 100
                    pil_font = get_cached_font(False, w_scale)
                raw_w = pil_font.getlength(text) if hasattr(pil_font, "getlength") else len(text) * 20
                w_len = raw_w * TIGHTNESS
                h_len = font_sz * (w_scale / 100.0)

                if current_line and current_w + space_width * 1.5 + w_len > max_line_width:
                    lines.append({"words": current_line, "width": current_w, "height": max_line_h})
                    current_line, current_w, max_line_h = [], 0, 0

                gap = space_width
                if use_karaoke and current_line:
                    # Leave room for either neighbour to pop without touching the other.
                    gap += (current_line[-1]["w"] + w_len) * (POP_SCALE - 1) / 2
                x_offset = current_w + gap if current_line else current_w
                current_line.append({
                    "text": text,
                    "plan": plan,
                    "w": w_len,
                    "x_offset": x_offset,
                    "start": max(0, w_dict["start"] - start_clip),
                    "end": min(clip_len, w_dict["end"] - start_clip),
                })
                current_w = x_offset + w_len
                max_line_h = max(max_line_h, h_len)

            if current_line:
                lines.append({"words": current_line, "width": current_w, "height": max_line_h})

            total_stack_h = sum(l["height"] for l in lines) + (len(lines) - 1) * LINE_SPACING
            current_y = play_res_y - margin_v - total_stack_h

            for line in lines:
                start_x = (play_res_x - line["width"]) / 2
                line_y = current_y + line["height"]

                for w_data in line["words"]:
                    word_x = start_x + w_data["x_offset"] + (w_data["w"] / 2)
                    t_start = int((w_data["start"] - seg_s) * 1000)
                    t_end = int((w_data["end"] - seg_s) * 1000)
                    t_pop = t_start + 80
                    t_settle = t_start + 160
                    plan = w_data["plan"]

                    if plan:
                        target_scale = get_scale_value(plan.get("scale_level", 2))
                        font_info = accent_font_dict if uses_accent_font(plan) else primary_font_dict
                        f_tag = build_font_tag(font_info)
                        c_tag = f"\\c{accent_color}"
                        w_anim = plan.get("animation", "bounce_pop")
                    else:
                        target_scale = 100
                        f_tag = build_font_tag(primary_font_dict)
                        c_tag = f"\\c{WHITE}"
                        w_anim = "none"

                    pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                    if use_karaoke:
                        # Group visible for the whole chunk; the spoken word pops,
                        # and (unless it is already a keyword) lights up.
                        pop = int(target_scale * POP_SCALE)
                        anim_tag = (
                            f"\\fscx{target_scale}\\fscy{target_scale}"
                            f"\\t({t_start},{t_pop},\\fscx{pop}\\fscy{pop})"
                            f"\\t({t_pop},{t_settle},\\fscx{target_scale}\\fscy{target_scale})"
                        )
                        if not plan:
                            anim_tag += (
                                f"\\t({t_start},{t_start},\\c{accent_color})"
                                f"\\t({t_end},{t_end},\\c{WHITE})"
                            )
                    elif w_anim == "stagger_up":
                        pos_tag = f"\\move({int(word_x)},{int(line_y + 30)},{int(word_x)},{int(line_y)},{t_start},{t_settle})"
                        anim_tag = f"\\alpha&HFF&\\fscx{target_scale}\\fscy{target_scale}\\t({t_start},{t_start},\\alpha&H00&)"
                    elif w_anim == "bounce_pop":
                        init_scale = int(target_scale * 0.7)
                        overshoot = int(target_scale * 1.15)
                        anim_tag = (
                            f"\\alpha&HFF&\\fscx{init_scale}\\fscy{init_scale}"
                            f"\\t({t_start},{t_start},\\alpha&H00&)"
                            f"\\t({t_start},{t_pop},\\fscx{overshoot}\\fscy{overshoot})"
                            f"\\t({t_pop},{t_settle},\\fscx{target_scale}\\fscy{target_scale})"
                        )
                    else:
                        anim_tag = f"\\alpha&HFF&\\fscx{target_scale}\\fscy{target_scale}\\t({t_start},{t_start},\\alpha&H00&)"

                    f.write(
                        f"Dialogue: 0,{_fmt_time(seg_s)},{_fmt_time(seg_e)},Default,,0,0,0,,"
                        f"{{\\an2{pos_tag}{f_tag}{c_tag}{anim_tag}}}{w_data['text']}\n"
                    )

                current_y += line["height"] + LINE_SPACING


def _write_simple(ass_file_name, header, data_segments, start_clip, clip_len,
                  use_karaoke, accent_color, show):
    """One Dialogue line per spoken word, re-drawing the whole group each time."""
    with open(ass_file_name, "w", encoding="utf-8") as f:
        f.write(header)
        for seg_index, seg in enumerate(data_segments):
            held_end = _held_end(data_segments, seg_index)
            seg_s = max(0, seg["start"] - start_clip)
            seg_e = min(clip_len, held_end - start_clip)
            if seg_s >= seg_e:
                continue

            words = seg["words"]
            for i, w in enumerate(words):
                w_s = max(0, w["start"] - start_clip)
                next_start = words[i + 1]["start"] if i < len(words) - 1 else held_end
                w_e = min(clip_len, next_start - start_clip)
                if w_s >= w_e:
                    continue

                parts = []
                for j, x in enumerate(words):
                    text = show(x["word"])
                    if use_karaoke:
                        parts.append(f"{{\\c{accent_color}}}{text}{{\\c{WHITE}}}" if j == i else text)
                    else:
                        parts.append(text if j <= i else f"{{\\alpha&HFF&}}{text}{{\\alpha&H00&}}")

                f.write(
                    f"Dialogue: 0,{_fmt_time(w_s)},{_fmt_time(w_e)},Default,,0,0,0,,{' '.join(parts)}\n"
                )
