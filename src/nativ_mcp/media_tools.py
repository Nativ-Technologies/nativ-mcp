"""MCP tools for audio, video, and subtitle localization."""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server import MCPServer


def register_media_tools(
    mcp: MCPServer,
    get_client: Any,
    read_local_file: Any,
    save_base64: Any,
) -> None:
    def _omit_media(payload: dict[str, Any]) -> dict[str, Any]:
        skip = {
            "audio_base64",
            "video_base64",
            "voice_audio_base64",
            "voice_video_base64",
            "bed_audio_base64",
            "source_voice_audio_base64",
            "srt_utf8",
        }
        return {k: v for k, v in payload.items() if k not in skip}

    @mcp.tool()
    async def transcribe_audio(
        file_path: str,
        source_language_code: str = "",
        keep_background_music: bool = False,
    ) -> str:
        """Transcribe speech from a local audio or video file (unbilled draft).

        Use the returned segments with `translate` (origin via text) then
        `synthesize_audio` to produce a dubbed track. Video uploads also
        return a video_id for muxing.

        Args:
            file_path: Path to audio (mp3, wav, m4a, …) or video (mp4, mov, …).
            source_language_code: Optional source language hint (e.g. "en").
            keep_background_music: If true, split a music bed for later remix.
        """
        client = get_client()
        data, filename, content_type = read_local_file(file_path)
        result = await client.transcribe_audio(
            data,
            filename,
            content_type,
            source_language_code=source_language_code or None,
            keep_background_music=keep_background_music,
        )
        slim = _omit_media(result)
        segments = slim.get("segments") or []
        lines = [
            f"**Transcript** ({slim.get('detected_language') or 'unknown'}, "
            f"{slim.get('duration_ms', 0)} ms):",
            slim.get("transcript", ""),
            "",
            f"Provider: {slim.get('provider')} · estimated credits: "
            f"{slim.get('estimated_credit_cost')} · billed seconds: "
            f"{slim.get('billed_seconds')}",
        ]
        if slim.get("video_id"):
            lines.append(f"video_id: {slim['video_id']}")
        if slim.get("stem_id"):
            lines.append(f"stem_id: {slim['stem_id']} · bed_mode: {slim.get('bed_mode')}")
        if segments:
            lines.append(f"\n**{len(segments)} segments:**")
            for seg in segments[:80]:
                lines.append(
                    f"- [{seg.get('start_ms')}–{seg.get('end_ms')} ms] {seg.get('text')}"
                )
            if len(segments) > 80:
                lines.append(f"… {len(segments) - 80} more segments omitted")
        return "\n".join(lines)

    @mcp.tool()
    async def parse_audio_script(file_path: str) -> str:
        """Parse a script file (.txt, .docx, .pdf, .srt, .itt) instead of STT."""
        client = get_client()
        data, filename, content_type = read_local_file(file_path)
        result = await client.parse_audio_script(data, filename, content_type)
        return json.dumps(_omit_media(result), indent=2, ensure_ascii=False)

    @mcp.tool()
    async def list_voices(language_code: str = "") -> str:
        """List TTS voices available for dubbing.

        Args:
            language_code: Optional filter (e.g. "fr", "ja-JP").
        """
        client = get_client()
        result = await client.list_voices(language_code or None)
        voices = result.get("voices") or []
        lines = [f"**{len(voices)} voices** (provider: {result.get('provider')})\n"]
        for v in voices:
            lines.append(
                f"- `{v.get('id')}` — {v.get('name')} ({v.get('gender')}, "
                f"{v.get('locale')}, {v.get('category')})"
            )
        return "\n".join(lines)

    @mcp.tool()
    async def preview_voice(
        voice_id: str,
        output_path: str,
        language_code: str = "",
        text: str = "",
    ) -> str:
        """Generate a short TTS preview and save it to disk.

        Args:
            voice_id: Voice id from `list_voices`.
            output_path: Where to write the WAV file.
            language_code: Optional locale.
            text: Optional preview line (max 200 chars).
        """
        client = get_client()
        result = await client.preview_voice(
            voice_id,
            language_code=language_code or None,
            text=text or None,
        )
        out = os.path.expanduser(output_path)
        save_base64(result.get("audio_base64", ""), out)
        return (
            f"Saved preview to {out} ({result.get('duration_ms')} ms, "
            f"{result.get('mime_type')}, provider {result.get('provider')})"
        )

    @mcp.tool()
    async def get_voice_consent_script(language_code: str = "") -> str:
        """Get the spoken consent script required for voice cloning."""
        client = get_client()
        result = await client.get_voice_consent_script(language_code or None)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def synthesize_audio(
        language: str,
        language_code: str,
        voice_id: str,
        segments: str,
        output_path: str,
        keep_same_length: bool = False,
        keep_background_music: bool = False,
        stem_id: str = "",
        source_duration_ms: int = 0,
        source_transcript: str = "",
        video_id: str = "",
        video_output_path: str = "",
    ) -> str:
        """Generate billed localized TTS (and optional dubbed video).

        Args:
            language: Target language name (e.g. "French").
            language_code: Target language code (e.g. "fr").
            voice_id: Voice id from `list_voices`.
            segments: JSON array of {text, start_ms, end_ms, original?} objects.
            output_path: Path to write the WAV audio.
            keep_same_length: Stretch/compress speech to source timings.
            keep_background_music: Mix transcribed music bed when stem_id is set.
            stem_id: Optional bed stem from `transcribe_audio`.
            source_duration_ms: Original duration.
            source_transcript: Optional original transcript.
            video_id: Optional id from transcribe/register to mux MP4.
            video_output_path: Optional path for dubbed MP4 when video_id is set.
        """
        try:
            parsed = json.loads(segments)
        except json.JSONDecodeError as exc:
            return f"`segments` must be a JSON array. Parse error: {exc}"
        if not isinstance(parsed, list) or not parsed:
            return "`segments` must be a non-empty JSON array."

        body: dict[str, Any] = {
            "language": language,
            "language_code": language_code,
            "voice_id": voice_id,
            "segments": parsed,
            "keep_same_length": keep_same_length,
            "keep_background_music": keep_background_music,
            "source_duration_ms": source_duration_ms,
            "tool": "api",
        }
        if stem_id:
            body["stem_id"] = stem_id
        if source_transcript:
            body["source_transcript"] = source_transcript
        if video_id:
            body["video_id"] = video_id

        client = get_client()
        result = await client.synthesize_audio(body)
        audio_out = os.path.expanduser(output_path)
        save_base64(result.get("audio_base64", ""), audio_out)
        lines = [
            f"**Dubbed audio saved:** {audio_out}",
            json.dumps(result.get("metadata") or {}, indent=2, ensure_ascii=False),
        ]
        video_b64 = result.get("video_base64")
        if video_b64:
            vout = os.path.expanduser(video_output_path) if video_output_path else (
                os.path.splitext(audio_out)[0] + ".mp4"
            )
            save_base64(video_b64, vout)
            lines.append(f"**Dubbed video saved:** {vout}")
        return "\n".join(lines)

    @mcp.tool()
    async def register_video(file_path: str) -> str:
        """Upload a source video for later remuxing. Returns video_id."""
        client = get_client()
        data, filename, content_type = read_local_file(file_path)
        result = await client.register_video(data, filename, content_type)
        return f"video_id: {result.get('video_id')}"

    @mcp.tool()
    async def remux_video(
        video_id: str,
        audio_path: str,
        output_path: str,
    ) -> str:
        """Mux a WAV file onto a previously registered video.

        Args:
            video_id: Id from `register_video` or `transcribe_audio`.
            audio_path: Local WAV (or other) file to encode as base64.
            output_path: Where to write the MP4.
        """
        import base64

        client = get_client()
        audio_bytes, _, _ = read_local_file(audio_path)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        result = await client.remux_video(video_id, audio_b64)
        out = os.path.expanduser(output_path)
        save_base64(result.get("video_base64", ""), out)
        return f"Saved remuxed video to {out} ({result.get('video_mime_type')})"

    @mcp.tool()
    async def parse_subtitle(file_path: str) -> str:
        """Parse a local SRT/ITT file into timed cues (no storage)."""
        client = get_client()
        data, filename, content_type = read_local_file(file_path)
        result = await client.parse_subtitle(data, filename, content_type)
        cues = result.get("cues") or []
        lines = [
            f"**{len(cues)} cues** · duration {result.get('duration_ms')} ms\n"
        ]
        for cue in cues[:100]:
            lines.append(
                f"- {cue.get('begin')} → {cue.get('end')}: {cue.get('text')}"
            )
        if len(cues) > 100:
            lines.append(f"… {len(cues) - 100} more cues omitted")
        return "\n".join(lines)

    @mcp.tool()
    async def localize_subtitles(
        target_language_codes: str,
        subtitle_path: str = "",
        video_path: str = "",
        glossary_path: str = "",
        source_language_code: str = "en",
        context: str = "",
        formality: str = "",
        output_dir: str = "",
    ) -> str:
        """Localize subtitles in-memory. Provide an SRT/ITT and/or a video (STT).

        Args:
            target_language_codes: Comma-separated codes (e.g. "fr,de,ja").
            subtitle_path: Optional local subtitle file.
            video_path: Optional video used when no subtitle file is given.
            glossary_path: Optional glossary text file.
            source_language_code: Source language code.
            context: Optional localization context.
            formality: Optional formality override.
            output_dir: If set, write one .srt per language there.
        """
        codes = [c.strip() for c in target_language_codes.split(",") if c.strip()]
        if not codes:
            return "Provide at least one target language code."
        if not subtitle_path and not video_path:
            return "Provide subtitle_path and/or video_path."

        subtitle = read_local_file(subtitle_path) if subtitle_path else None
        video = read_local_file(video_path) if video_path else None
        glossary = read_local_file(glossary_path) if glossary_path else None
        client = get_client()
        result = await client.localize_subtitles(
            codes,
            subtitle=subtitle,
            video=video,
            glossary=glossary,
            source_language_code=source_language_code,
            context=context,
            formality=formality or None,
        )
        lines = [
            f"**Localized subtitles** ({result.get('filename')}, "
            f"{result.get('duration_ms')} ms)"
        ]
        if result.get("video_id"):
            lines.append(f"video_id: {result['video_id']}")
        out_dir = os.path.expanduser(output_dir) if output_dir else ""
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        for lang in result.get("languages") or []:
            code = lang.get("language_code") or "lang"
            srt = lang.get("srt_utf8") or ""
            lines.append(
                f"\n**{lang.get('language')} ({code})** — {len(lang.get('cues') or [])} cues"
            )
            if out_dir and srt:
                path = os.path.join(out_dir, f"{code}.srt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(srt)
                lines.append(f"Saved {path}")
            else:
                preview = "\n".join(
                    f"- {c.get('original')} → {c.get('translated')}"
                    for c in (lang.get("cues") or [])[:20]
                )
                if preview:
                    lines.append(preview)
        return "\n".join(lines)
