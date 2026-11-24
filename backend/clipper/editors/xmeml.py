"""FCP7 XML (xmeml) export.

This is the format Premiere and Resolve actually open without a plugin, and it is
also what FilmCraft's importer is built around. It is verbose, unforgiving, and
counts everything in frames, so all of the arithmetic comes from
``editors.timecode`` rather than being re-derived here.

Two details that break imports when they are wrong:

* ``<pathurl>`` must be a percent-encoded ``file://`` URL - a Windows path with
  spaces pasted straight in gives an offline clip in Premiere;
* ``<in>``/``<out>`` are source frames while ``<start>``/``<end>`` are timeline
  frames. Swapping them produces a timeline that looks right and plays the wrong
  part of the file.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .spec import ClipSpec


def _rate_xml(spec: ClipSpec, indent: str) -> str:
    rate = spec.rate
    ntsc = "TRUE" if abs(rate.fps - rate.nominal) > 0.01 else "FALSE"
    return (
        f"{indent}<rate><timebase>{rate.nominal}</timebase>"
        f"<ntsc>{ntsc}</ntsc></rate>"
    )


def _clipitem(spec: ClipSpec, index: int, record_in: int) -> str:
    record_out = record_in + spec.duration_frames
    file_id = f"file-{index}"
    marker = ""
    if spec.hook:
        marker = (
            "\n          <marker>"
            f"<name>{escape(spec.hook[:80])}</name>"
            "<in>-1</in><out>-1</out>"
            "</marker>"
        )
    return f"""      <clipitem id="clipitem-{index}">
        <name>{escape(spec.name)}</name>
        <duration>{max(1, int(round(spec.source_duration * spec.rate.fps)))}</duration>
{_rate_xml(spec, "        ")}
        <start>{record_in}</start>
        <end>{record_out}</end>
        <in>{spec.in_frame}</in>
        <out>{spec.out_frame}</out>
        <file id="{file_id}">
          <name>{escape(spec.source_name)}</name>
          <pathurl>{escape(spec.file_url())}</pathurl>
{_rate_xml(spec, "          ")}
          <duration>{max(1, int(round(spec.source_duration * spec.rate.fps)))}</duration>
          <media>
            <video>
              <samplecharacteristics>
{_rate_xml(spec, "                ")}
                <width>{spec.width or 1920}</width>
                <height>{spec.height or 1080}</height>
                <anamorphic>FALSE</anamorphic>
                <pixelaspectratio>square</pixelaspectratio>
              </samplecharacteristics>
            </video>
          </media>
        </file>
        <logginginfo>
          <description>{escape(spec.hook[:160])}</description>
        </logginginfo>{marker}
      </clipitem>"""


def build(specs: list[ClipSpec], name: str = "Clip Factory reel") -> str:
    total = sum(spec.duration_frames for spec in specs)
    reference = specs[0] if specs else None
    width = reference.width if reference else 1920
    height = reference.height if reference else 1080

    items: list[str] = []
    record_in = 0
    for index, spec in enumerate(specs, start=1):
        items.append(_clipitem(spec, index, record_in))
        record_in += spec.duration_frames

    rate_block = _rate_xml(reference, "        ") if reference else (
        "        <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>"
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="5">
  <sequence id="sequence-1">
    <name>{escape(name)}</name>
    <duration>{max(1, total)}</duration>
{rate_block}
    <timecode>
      <rate><timebase>{reference.rate.nominal if reference else 30}</timebase></rate>
      <string>00:00:00:00</string>
      <frame>0</frame>
      <displayformat>NDF</displayformat>
    </timecode>
    <media>
      <video>
        <format>
          <samplecharacteristics>
{rate_block}
            <width>{width}</width>
            <height>{height}</height>
            <anamorphic>FALSE</anamorphic>
            <pixelaspectratio>square</pixelaspectratio>
          </samplecharacteristics>
        </format>
        <track>
{chr(10).join(items)}
        </track>
      </video>
    </media>
  </sequence>
</xmeml>
"""
