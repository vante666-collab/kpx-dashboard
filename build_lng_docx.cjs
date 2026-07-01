const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  ExternalHyperlink, Footer, PageNumber, LevelFormat
} = require("docx");

const FONT = "맑은 고딕";
const CW = 9026;                 // A4 content width (1" margins)
const navy = "1F3864", blue = "2E75B6", lightblue = "D9E2F3", gray = "F2F2F2";
const bd = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: bd, bottom: bd, left: bd, right: bd, insideHorizontal: bd, insideVertical: bd };

const T = (t, o = {}) => new TextRun({ text: t, font: FONT, ...o });
const P = (children, o = {}) => new Paragraph({ children: Array.isArray(children) ? children : [children], ...o });

function cell(text, { w, head = false, bold = false, align = AlignmentType.LEFT, fill } = {}) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    shading: { fill: fill || (head ? blue : "FFFFFF"), type: ShadingType.CLEAR },
    margins: { top: 70, bottom: 70, left: 120, right: 120 },
    children: [P(T(text, { bold: head || bold, color: head ? "FFFFFF" : "000000", size: 19 }), { alignment: align })],
  });
}
function table(widths, rows) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: widths, borders,
    rows: rows.map((r, ri) => new TableRow({
      children: r.map((c, ci) => typeof c === "object"
        ? cell(c.t, { w: widths[ci], head: ri === 0, align: c.a, bold: c.b, fill: c.fill })
        : cell(c, { w: widths[ci], head: ri === 0, align: ci === 0 ? AlignmentType.LEFT : AlignmentType.CENTER }))
    }))
  });
}
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [T(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [T(t)] });
const BULLET = (runs) => new Paragraph({ numbering: { reference: "b", level: 0 }, children: Array.isArray(runs) ? runs : [T(runs)] });

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: navy },
        paragraph: { spacing: { before: 260, after: 120 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: blue, space: 2 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: FONT, color: navy },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 1 } },
    ]
  },
  numbering: { config: [{ reference: "b", levels: [
    { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 460, hanging: 240 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [ new Paragraph({ alignment: AlignmentType.CENTER,
      children: [ T("관세·개별소비세 인하 영향 분석   ·   ", { size: 16, color: "808080" }),
        new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "808080" }) ] }) ] }) },
    children: [
      // 표지 제목
      new Paragraph({ spacing: { after: 60 }, children: [T("LNG 관세·개별소비세 인하가", { bold: true, size: 36, color: navy })] }),
      new Paragraph({ spacing: { after: 160 }, children: [T("LNG 복합발전 손익에 미치는 영향", { bold: true, size: 36, color: navy })] }),
      new Paragraph({ spacing: { after: 30 }, children: [T("대상 조치: 발전용 LNG 할당관세 0% + 개별소비세 15% 감면 (2026년 하반기)", { size: 20, color: "595959" })] }),
      new Paragraph({ spacing: { after: 200 }, children: [T("작성일 2026.06.19   ·   전력시장(CBP) 구조 기반 분석", { size: 18, color: "808080" })] }),

      // 요약 박스
      new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: [CW],
        borders: { top: { style: BorderStyle.SINGLE, size: 4, color: blue }, bottom: { style: BorderStyle.SINGLE, size: 4, color: blue }, left: { style: BorderStyle.SINGLE, size: 18, color: blue }, right: { style: BorderStyle.SINGLE, size: 4, color: blue } },
        rows: [ new TableRow({ children: [ new TableCell({ width: { size: CW, type: WidthType.DXA }, shading: { fill: lightblue, type: ShadingType.CLEAR }, margins: { top: 140, bottom: 140, left: 200, right: 200 }, children: [
          P([T("핵심 요약  ", { bold: true, color: navy, size: 22 })]),
          P([T("두 조치로 하반기 발전용 LNG 변동비가 약 ", {}), T("2.5~4원/kWh", { bold: true, color: blue }), T(" 내려가지만, 한국 전력시장(CBP)에서는 ", {}), T("SMP도 같은 폭으로 하락", { bold: true }), T("하므로 시장정산 LNG 복합발전의 ", {}), T("마진(SMP−변동비)은 거의 중립", { bold: true, color: "C00000" }), T("입니다.", {})], { spacing: { before: 60 } }),
          P([T("실질 수혜는 ① 전기소비자(SMP·요금 안정), ② 직수입·고정가격계약·열병합 비중이 큰 발전사입니다.", {})], { spacing: { before: 40 } }),
        ] }) ] }) ] }),
      P([], { spacing: { after: 80 } }),

      // 1. 정책 조치
      H1("1. 정책 조치 요약"),
      table([2300, 3600, 3126], [
        [{t:"구분",a:AlignmentType.CENTER},{t:"내용",a:AlignmentType.CENTER},{t:"적용 시점·대상",a:AlignmentType.CENTER}],
        [{t:"관세(할당관세)",b:true},{t:"기본 3% → 0% (당초 3Q 2%·4Q 1% 계획을 0%로 확대)"},{t:"2026 하반기 / 발전용 LNG·LPG 등"}],
        [{t:"개별소비세",b:true},{t:"발전용 LNG 15% 감면"},{t:"2026.7~12월 / 발전용 LNG"}],
      ]),
      P([T("※ 기사에 LNG 개별소비세 단가(원/kg)·관세 부과기준 금액은 명시되지 않아, 아래 절감액은 일반 가정으로 추정함.", { size: 17, color: "808080", italics: true })], { spacing: { before: 60 } }),

      // 2. 변동비 절감 규모
      H1("2. 연료비(변동비) 절감 규모 추정"),
      table([3000, 3413, 2613], [
        [{t:"조치",a:AlignmentType.CENTER},{t:"가정",a:AlignmentType.CENTER},{t:"변동비 인하",a:AlignmentType.CENTER}],
        [{t:"관세 3%→0%",b:true},{t:"LNG CIF ~700~750원/kg × 3% ≈ 22~25원/kg, 소비율 ~123kg/MWh"},{t:"약 2~4원/kWh",b:true,a:AlignmentType.CENTER}],
        [{t:"개소세 −15%",b:true},{t:"현행 ~12원/kg 가정 × 15% ≈ 1.8원/kg (단가 미명시)"},{t:"약 0.2원/kWh",a:AlignmentType.CENTER}],
        [{t:"합계",b:true,fill:gray},{t:"관세가 주효과, 개소세는 부차적",fill:gray},{t:"약 2.5~4원/kWh",b:true,a:AlignmentType.CENTER,fill:gray}],
      ]),

      // 3. 핵심 결론
      H1("3. 핵심 결론 — 시장정산 마진은 거의 중립"),
      P([T("한국 전력시장은 ", {}), T("SMP를 LNG 한계발전기의 변동비가 결정", { bold: true }), T("합니다. 관세·개소세 인하가 ", {}), T("모든 발전용 LNG에 동일", { bold: true }), T("하게 적용되므로:", {})]),
      BULLET([T("모든 LNG의 변동비 하락 → ", {}), T("SMP도 같은 폭으로 하락", { bold: true, color: blue })]),
      BULLET([T("LNG 복합의 마진 = SMP − 변동비 → ", {}), T("분자·분모가 함께 하락 → 마진 거의 불변", { bold: true })]),
      BULLET([T("절감분(~3원/kWh)은 대부분 ", {}), T("SMP 하락으로 전기소비자에게 귀착", { bold: true, color: "C00000" })]),
      P([T("두 기사 모두 정책 목적을 ", {}), T("‘소비자물가·전기요금 안정’", { bold: true }), T("(소비자물가 5월 3.1% 맥락)으로 제시한 점도, 수혜가 발전마진이 아니라 소비자라는 시장구조 분석과 일치합니다.", {})], { spacing: { before: 60 } }),

      // 4. 손익이 실제 움직이는 경우
      H1("4. 그래도 발전사 손익이 움직이는 경우"),
      table([3100, 1500, 4426], [
        [{t:"구분",a:AlignmentType.CENTER},{t:"방향",a:AlignmentType.CENTER},{t:"이유",a:AlignmentType.CENTER}],
        [{t:"고정가격계약·PPA",b:true},{t:"이익 ↑",a:AlignmentType.CENTER},{t:"매출은 계약가 고정, 연료비만 하락"}],
        [{t:"열병합(CHP) 열 매출",b:true},{t:"이익 ↑",a:AlignmentType.CENTER},{t:"열 매출은 SMP 무관 → 연료비↓가 그대로 마진"}],
        [{t:"LNG 직수입 발전사",b:true},{t:"이익 ↑",a:AlignmentType.CENTER},{t:"관세·개소세를 직접 절감(시장정산과 별개)"}],
        [{t:"비효율 노후 LNG",b:true},{t:"소폭 ↑",a:AlignmentType.CENTER},{t:"변동비↓로 급전기회·가동률 증가 가능"}],
        [{t:"제약발전(constrained-on)",b:true},{t:"소폭 ↓",a:AlignmentType.CENTER},{t:"변동비로 정산 → 연료비↓ = 정산금↓"}],
        [{t:"순수 한계 LNG 복합",b:true},{t:"중립",a:AlignmentType.CENTER},{t:"SMP = 자기 변동비라 마진 0 유지"}],
      ]),

      // 5. 정량화 관건/한계
      H1("5. 정량화의 관건과 한계"),
      BULLET([T("관세 부과기준(CIF)·환율·heat rate·LNG 가격에 따라 절감폭(2~4원/kWh)이 달라짐 — 관세가 핵심 변수", {})]),
      BULLET([T("발전용 LNG 개별소비세 실제 적용단가가 확인되면 0.2원/kWh 추정치를 정밀화 가능", {})]),
      BULLET([T("회사별 ", {}), T("(시장정산 vs 계약물량 vs 열 매출)", { bold: true }), T(" 비중이 최종 손익을 결정 — 시장정산 위주는 중립, 계약·열·직수입 비중이 크면 플러스", {})]),

      // 출처
      H2("출처"),
      P([T("• 세계일보 (2026.06.18): ", { size: 18, color: "595959" }), new ExternalHyperlink({ link: "https://www.segye.com/newsView/20260618516134", children: [new TextRun({ text: "관세 0% 관련", style: "Hyperlink", font: FONT, size: 18 })] })]),
      P([T("• 노컷뉴스 (2026.06.18): ", { size: 18, color: "595959" }), new ExternalHyperlink({ link: "https://www.nocutnews.co.kr/news/6534778", children: [new TextRun({ text: "발전용 LNG 개별소비세 15% 감면 관련", style: "Hyperlink", font: FONT, size: 18 })] })]),

      P([T("본 문서는 일반적인 정책·산업 영향 분석이며 특정 종목에 대한 투자 권유가 아닙니다. 회사별 정확한 손익 산정에는 연료계약 조건·계약물량 비중·열 매출 자료가 필요합니다.", { size: 16, italics: true, color: "808080" })], { spacing: { before: 200 } }),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  const out = "C:\\Users\\admin.SKENS-T1012-05\\Desktop\\LNG_관세_개소세_손익영향.docx";
  fs.writeFileSync(out, buf);
  console.log("WROTE", out, buf.length, "bytes");
});
