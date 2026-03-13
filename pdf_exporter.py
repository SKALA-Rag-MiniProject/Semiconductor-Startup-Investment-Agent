"""마크다운 보고서 → PDF 변환 모듈.

fpdf2를 사용하여 마크다운을 직접 파싱 후 PDF로 출력한다.
시스템 의존성 없이 동작하며 한글을 지원한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF


# ── 한글 폰트 자동 탐색 ──
_PROJECT_FONTS_DIR = Path(__file__).parent / "fonts"

_FONT_CANDIDATES_REGULAR = [
    _PROJECT_FONTS_DIR / "NanumGothic.ttf",
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
]

_FONT_CANDIDATES_BOLD = [
    _PROJECT_FONTS_DIR / "NanumGothicBold.ttf",
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
]


def _find_font(candidates: list[Path]) -> str:
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


class ReportPDF(FPDF):
    """투자 보고서용 커스텀 PDF 클래스."""

    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

        # 한글 폰트 등록
        regular = _find_font(_FONT_CANDIDATES_REGULAR)
        bold = _find_font(_FONT_CANDIDATES_BOLD)
        if regular:
            self.add_font("Korean", "", regular, uni=True)
            self.add_font("Korean", "B", bold if bold else regular, uni=True)
            self._font_name = "Korean"
        else:
            self._font_name = "Helvetica"

    def header(self) -> None:
        self.set_font(self._font_name, "B", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, "CONFIDENTIAL | AI 스타트업 투자 에이전트", align="C", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(self._font_name, "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"{self.page_no()} / {{nb}}", align="C")

    # ── 렌더링 헬퍼 ──

    def _set_body(self, size: int = 10) -> None:
        self.set_font(self._font_name, "", size)
        self.set_text_color(30, 30, 30)

    def _set_bold(self, size: int = 10) -> None:
        self.set_font(self._font_name, "B", size)
        self.set_text_color(30, 30, 30)

    def _write_h1(self, text: str) -> None:
        if self.page_no() > 1:
            self.add_page()
        self.set_font(self._font_name, "B", 18)
        self.set_text_color(22, 33, 62)
        self.cell(0, 12, text, new_x="LMARGIN", new_y="NEXT")
        # 밑줄
        y = self.get_y()
        self.set_draw_color(22, 33, 62)
        self.set_line_width(0.8)
        self.line(10, y, 200, y)
        self.ln(6)

    def _write_h2(self, text: str) -> None:
        self.ln(4)
        self.set_font(self._font_name, "B", 14)
        self.set_text_color(22, 33, 62)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.3)
        self.line(10, y, 200, y)
        self.ln(3)

    def _write_h3(self, text: str) -> None:
        self.ln(2)
        self.set_font(self._font_name, "B", 11)
        self.set_text_color(15, 52, 96)
        self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def _write_blockquote(self, text: str) -> None:
        """SUMMARY / 투자의견 박스."""
        self._set_body(10)
        lines = [l for l in text.split("\n") if l.strip()]
        box_h = max(len(lines) * 7 + 10, 16)

        y = self.get_y()
        # 페이지 넘김 체크
        if y + box_h > self.h - self.b_margin:
            self.add_page()
            y = self.get_y()

        self.set_fill_color(238, 243, 255)
        self.set_draw_color(59, 130, 246)
        self.rect(10, y, 190, box_h, style="F")
        self.set_line_width(0.8)
        self.line(10, y, 10, y + box_h)
        self.set_xy(16, y + 4)
        for line in lines:
            self._set_body(9)
            self.cell(170, 6, line[:120], new_x="LMARGIN", new_y="NEXT")
            self.set_x(16)
        self.set_y(y + box_h + 4)

    def _write_table(self, header: list[str], rows: list[list[str]]) -> None:
        """마크다운 테이블 렌더링 (동적 열 폭)."""
        col_count = len(header)
        if col_count == 0:
            return

        # 열 폭: 첫 열(항목명)을 넓게, 나머지 균등
        if col_count >= 5:
            first_w = 50
            rest_w = (190 - first_w) / (col_count - 1)
            col_widths = [first_w] + [rest_w] * (col_count - 1)
        else:
            col_widths = [190 / col_count] * col_count

        font_size = 8 if col_count >= 6 else 9

        # 헤더
        self.set_fill_color(22, 33, 62)
        self.set_text_color(255, 255, 255)
        self.set_font(self._font_name, "B", font_size)
        for j, h in enumerate(header):
            self.cell(col_widths[j], 7, h.strip(), border=1, fill=True, align="C")
        self.ln()

        # 행
        self.set_text_color(30, 30, 30)
        for i, row in enumerate(rows):
            if i % 2 == 0:
                self.set_fill_color(248, 249, 250)
            else:
                self.set_fill_color(255, 255, 255)

            # 마지막 행 (종합 점수) 강조
            if i == len(rows) - 1 and "종합" in "".join(row):
                self.set_fill_color(240, 244, 255)
                self.set_font(self._font_name, "B", font_size)
            else:
                self.set_font(self._font_name, "", font_size)

            for j, cell_text in enumerate(row):
                w = col_widths[j] if j < len(col_widths) else col_widths[-1]
                self.cell(w, 6, cell_text.strip(), border=1, fill=True, align="C")
            self.ln()
        self.ln(3)

    def _write_bullet(self, text: str) -> None:
        self._set_body(10)
        self.set_x(14)
        self.cell(5, 6, "-")
        # 긴 텍스트는 잘라서 출력
        remaining_w = 175
        if self.get_string_width(text) < remaining_w:
            self.cell(remaining_w, 6, text, new_x="LMARGIN", new_y="NEXT")
        else:
            self.multi_cell(remaining_w, 6, text)

    def _write_risk_item(self, level: str, rest: str) -> None:
        """**HIGH** | 제목 형태의 리스크 항목."""
        colors = {
            "HIGH": (192, 57, 43),
            "MED": (230, 126, 34),
            "LOW": (46, 204, 113),
        }
        r, g, b = colors.get(level, (100, 100, 100))
        self.set_font(self._font_name, "B", 10)
        self.set_text_color(r, g, b)
        self.cell(16, 6, f"[{level}]")
        self._set_body(10)
        self.cell(0, 6, rest, new_x="LMARGIN", new_y="NEXT")

    def _write_hr(self) -> None:
        self.ln(3)
        y = self.get_y()
        self.set_draw_color(22, 33, 62)
        self.set_line_width(0.5)
        self.line(10, y, 200, y)
        self.ln(5)


def _parse_table(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int]:
    """마크다운 테이블을 파싱한다. (header, rows, end_index)."""
    header_line = lines[start]
    header = [c.strip() for c in header_line.strip("|").split("|")]

    # separator 라인 건너뛰기
    idx = start + 1
    if idx < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[idx].strip()):
        idx += 1

    rows = []
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        cells = [c.strip() for c in lines[idx].strip("|").split("|")]
        rows.append(cells)
        idx += 1

    return header, rows, idx


def markdown_to_pdf(md_text: str, output_path: str | Path) -> Path:
    """마크다운 보고서를 PDF로 변환한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    lines = md_text.split("\n")
    i = 0
    blockquote_buf: list[str] = []
    in_blockquote = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # blockquote 종료
        if in_blockquote and not stripped.startswith(">"):
            pdf._write_blockquote("\n".join(blockquote_buf))
            blockquote_buf = []
            in_blockquote = False

        # 빈 줄
        if not stripped:
            i += 1
            continue

        # --- 구분선
        if stripped == "---":
            pdf._write_hr()
            i += 1
            continue

        # # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            pdf._write_h1(stripped[2:])
            i += 1
            continue

        # ## H2
        if stripped.startswith("## "):
            pdf._write_h2(stripped[3:])
            i += 1
            continue

        # ### H3
        if stripped.startswith("### "):
            pdf._write_h3(stripped[4:])
            i += 1
            continue

        # 테이블
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            header, rows, end = _parse_table(lines, i)
            pdf._write_table(header, rows)
            i = end
            continue

        # blockquote
        if stripped.startswith(">"):
            in_blockquote = True
            blockquote_buf.append(stripped[1:].strip())
            i += 1
            continue

        # 리스크 항목: **HIGH** | ...
        risk_match = re.match(r"^\*\*(\w+)\*\*\s*\|\s*(.+)", stripped)
        if risk_match:
            pdf._write_risk_item(risk_match.group(1), risk_match.group(2))
            i += 1
            continue

        # 불릿
        if stripped.startswith("- "):
            # 볼드 처리 제거 후 출력
            text = stripped[2:]
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            pdf._write_bullet(text)
            i += 1
            continue

        # 볼드 라인
        if stripped.startswith("**") and stripped.endswith("**"):
            pdf._set_bold(10)
            pdf.cell(0, 6, stripped.strip("*")[:150], new_x="LMARGIN", new_y="NEXT")
            i += 1
            continue

        # 일반 텍스트
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        pdf._set_body(10)
        pdf.cell(0, 6, text[:150], new_x="LMARGIN", new_y="NEXT")
        i += 1

    # 남은 blockquote
    if in_blockquote and blockquote_buf:
        pdf._write_blockquote("\n".join(blockquote_buf))

    pdf.output(str(output_path))
    return output_path
