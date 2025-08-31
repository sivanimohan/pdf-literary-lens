package com.kongole.stirlingproxy.service;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.interactive.documentnavigation.outline.*;
import org.apache.pdfbox.text.PDFTextStripper;
import java.util.regex.Matcher;
import org.apache.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageDestination;
import java.io.InputStream;
import java.util.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

@Service
public class PdfHeadingDetectionService {
    // ...existing code...
    // Manual mapping support: allow user to provide a map of page numbers to headings
    private Map<Integer, String> manualHeadingMap = new HashMap<>();

    public void setManualHeadingMap(Map<Integer, String> manualMap) {
        this.manualHeadingMap = manualMap;
    }

    // Removed unused PAGE_LABEL_PATTERN field
    // Simplified regex: only matches generic heading patterns, not specific chapter titles
    private static final Pattern HEADING_REGEX = Pattern.compile(
        "^(CHAPTER|SECTION|PART|UNIT)\\s+([0-9]+|[IVXLCDM]+)?(\\s*[:\\-].*)?$",
        Pattern.CASE_INSENSITIVE
    );
    private static final String[] EXTRA_KEYWORDS = {
        "prologue", "epilogue", "introduction", "preface", "foreword"
    };

    public static class Heading {
        private String text;
        private int page;
        private float fontSize;
        private float yPosition;
        private float whitespaceAbove;
        private float whitespaceBelow;
        private float headingScore;
        public Heading(String text, int page, float fontSize, float yPosition,
                       float whitespaceAbove, float whitespaceBelow, float headingScore) {
            this.text = text;
            this.page = page;
            this.fontSize = fontSize;
            this.yPosition = yPosition;
            this.whitespaceAbove = whitespaceAbove;
            this.whitespaceBelow = whitespaceBelow;
            this.headingScore = headingScore;
        }
        public String getText() { return text; }
        public int getPage() { return page; }
        public float getFontSize() { return fontSize; }
        public float getYPosition() { return yPosition; }
        public float getWhitespaceAbove() { return whitespaceAbove; }
        public float getWhitespaceBelow() { return whitespaceBelow; }
        public float getHeadingScore() { return headingScore; }
    }

    public List<Heading> detectHeadings(InputStream pdfStream, List<String> customKeywords) {
        List<Heading> candidateHeadings = new ArrayList<>();
        List<String> logs = new ArrayList<>();
        try {
            try (PDDocument document = PDDocument.load(pdfStream)) {
                // 1. Bookmarks/Outline Extraction
                PDDocumentOutline outline = document.getDocumentCatalog().getDocumentOutline();
                if (outline != null) {
                    PDOutlineItem current = outline.getFirstChild();
                    while (current != null) {
                        String title = current.getTitle();
                        int pageNum = -1;
                        try {
                            if (current.getDestination() != null) {
                                if (current.getDestination() instanceof PDPageDestination) {
                                    PDPageDestination pd = (PDPageDestination) current.getDestination();
                                    if (pd.getPage() != null) {
                                        pageNum = document.getPages().indexOf(pd.getPage()) + 1;
                                    } else if (pd.getPageNumber() >= 0) {
                                        pageNum = pd.getPageNumber() + 1;
                                    }
                                }
                            } else if (current.getAction() instanceof org.apache.pdfbox.pdmodel.interactive.action.PDActionGoTo) {
                                org.apache.pdfbox.pdmodel.interactive.action.PDActionGoTo action = (org.apache.pdfbox.pdmodel.interactive.action.PDActionGoTo) current.getAction();
                                if (action.getDestination() instanceof PDPageDestination) {
                                    PDPageDestination pd = (PDPageDestination) action.getDestination();
                                    if (pd.getPage() != null) {
                                        pageNum = document.getPages().indexOf(pd.getPage()) + 1;
                                    } else if (pd.getPageNumber() >= 0) {
                                        pageNum = pd.getPageNumber() + 1;
                                    }
                                }
                            }
                        } catch (Exception e) {
                            pageNum = -1;
                            logs.add("[ERROR] Failed to resolve outline page for title '" + title + "': " + e.getMessage());
                        }
                        if (isProbableHeadingUniversal(title, 14, 0, 800, 100, customKeywords, 14, false)) {
                            float score = scoreHeading(title, 14, 0, 800, 100, customKeywords, 14);
                            candidateHeadings.add(new Heading(title, pageNum, 14, 0, 100, 0, score));
                        }
                        current = current.getNextSibling();
                    }
                }

                // 2. TOC Page Parsing (first 15 pages)
                PDFTextStripper tocStripper = new PDFTextStripper();
                tocStripper.setStartPage(1);
                tocStripper.setEndPage(Math.min(15, document.getNumberOfPages()));
                String tocText = tocStripper.getText(document);
                String[] tocLines = tocText.split("\r?\n");
                Pattern tocPattern = Pattern.compile("^(.*?)(\\.\\.{2,}|\\s{2,})(\\d+)$");
                for (String line : tocLines) {
                    Matcher m = tocPattern.matcher(line.trim());
                    if (m.find()) {
                        String title = m.group(1).trim();
                        int pageNum = Integer.parseInt(m.group(3));
                        if (isProbableHeadingUniversal(title, 14, 0, 800, 100, customKeywords, 14, false)) {
                            float score = scoreHeading(title, 14, 0, 800, 100, customKeywords, 14);
                            candidateHeadings.add(new Heading(title, pageNum, 14, 0, 100, 0, score));
                        }
                    }
                }

                // 3. Text-based Heading Detection (Font, Position, Regex, etc.)
                float[] avgFontSize = {0};
                int[] count = {0};
                Map<Integer, Boolean> foundOnPage = new HashMap<>();
                PDFTextStripper headingStripper = new PDFTextStripper() {
                    float lastY = -1;
                    int lastPage = -1;
                    @Override
                    protected void writeString(String string, List<org.apache.pdfbox.text.TextPosition> textPositions) {
                        if (textPositions.isEmpty()) return;
                        float fontSize = textPositions.get(0).getFontSizeInPt();
                        String fontName = textPositions.get(0).getFont().getName();
                        boolean isBold = false;
                        if (fontName != null) {
                            String fontNameLower = fontName.toLowerCase();
                            isBold = fontNameLower.contains("bold") || fontNameLower.contains("black");
                        }
                        float y = textPositions.get(0).getY();
                        int page = getCurrentPageNo();
                        float whitespaceAbove = (lastPage == page) ? Math.abs(y - lastY) : 100;
                        avgFontSize[0] += fontSize;
                        count[0]++;
                        String line = string.trim();
                        boolean probable = isProbableHeadingUniversal(line, (int)fontSize, (int)y, (int)document.getPage(page - 1).getMediaBox().getHeight(),
                                (int)whitespaceAbove, customKeywords, (count[0] > 0 ? (int)(avgFontSize[0] / count[0]) : 14), isBold);
                        boolean fallback = false;
                        if (!foundOnPage.getOrDefault(page, false)) {
                            if ((isBold || fontSize >= (count[0] > 0 ? avgFontSize[0] / count[0] : 14)) && y < document.getPage(page - 1).getMediaBox().getHeight() * 0.33) {
                                fallback = true;
                                foundOnPage.put(page, true);
                            }
                        }
                        if (probable || fallback) {
                            float score = scoreHeading(line, fontSize, y,
                                    document.getPage(page - 1).getMediaBox().getHeight(),
                                    whitespaceAbove, customKeywords,
                                    (count[0] > 0 ? avgFontSize[0] / count[0] : 14));
                            candidateHeadings.add(new Heading(line, page, fontSize, y, whitespaceAbove, 0, score));
                        }
                        lastY = y;
                        lastPage = page;
                    }
                };
                headingStripper.setSortByPosition(true);
                headingStripper.getText(document);

                // 4. OCR Fallback
                if (candidateHeadings.isEmpty()) {
                    candidateHeadings.addAll(detectHeadingsWithOCR(document, customKeywords));
                }

                // 5. Manual Mapping Override
                if (manualHeadingMap != null && !manualHeadingMap.isEmpty()) {
                    for (Map.Entry<Integer, String> entry : manualHeadingMap.entrySet()) {
                        candidateHeadings.add(new Heading(entry.getValue(), entry.getKey(), 14, 0, 100, 0, 1.0f));
                    }
                }

                // 6. Ensemble: Deduplicate and Sort
                Map<String, Heading> uniqueHeadings = new LinkedHashMap<>();
                for (Heading h : candidateHeadings) {
                    String key = h.getText().trim().toLowerCase() + "@" + h.getPage();
                    if (!uniqueHeadings.containsKey(key)) {
                        uniqueHeadings.put(key, h);
                    }
                }
                List<Heading> headings = new ArrayList<>(uniqueHeadings.values());
                headings.sort((a, b) -> Float.compare(b.getHeadingScore(), a.getHeadingScore()));
                return headings;
            }
        } catch (Exception e) {
            // ...existing error handling...
        }
        return new ArrayList<>();
    }

    // OCR fallback method
    private List<Heading> detectHeadingsWithOCR(PDDocument document, List<String> customKeywords) {
        List<Heading> headings = new ArrayList<>();
        try {
            org.apache.pdfbox.rendering.PDFRenderer pdfRenderer = new org.apache.pdfbox.rendering.PDFRenderer(document);
            net.sourceforge.tess4j.ITesseract tesseract = new net.sourceforge.tess4j.Tesseract();
            tesseract.setDatapath("tessdata");
            tesseract.setLanguage("eng");
            for (int page = 0; page < document.getNumberOfPages(); page++) {
                java.awt.image.BufferedImage bim = pdfRenderer.renderImageWithDPI(page, 300);
                String ocrText = tesseract.doOCR(bim);
                String[] lines = ocrText.split("\r?\n");
                for (String line : lines) {
                    String trimmed = line.trim();
                    if (isProbableHeadingUniversal(trimmed, 14, 0, 800, 100, customKeywords, 14, false)) {
                        float score = scoreHeading(trimmed, 14, 0, 800, 100, customKeywords, 14);
                        headings.add(new Heading(trimmed, page + 1, 14, 0, 100, 0, score));
                    }
                }
            }
        } catch (Exception ignore) {}
        return headings;
    }

    private float scoreHeading(String text, float fontSize, float yPos, float pageHeight,
                               float whitespaceAbove, List<String> customKeywords, float avgFont) {
        float score = 0;
        if (fontSize >= avgFont + 2) score += 0.4;
        if (yPos < pageHeight * 0.25) score += 0.2;
        if (HEADING_REGEX.matcher(text.toUpperCase()).matches()) score += 0.3;
        for (String kw : EXTRA_KEYWORDS) {
            if (text.equalsIgnoreCase(kw) || text.toLowerCase().startsWith(kw + " ")) score += 0.2;
        }
        if (customKeywords != null) {
            for (String kw : customKeywords) {
                if (text.toLowerCase().contains(kw.toLowerCase())) score += 0.2;
            }
        }
        if (whitespaceAbove > 20) score += 0.1;
        return score;
    }

    // Added missing method
    private boolean isProbableHeadingUniversal(String text, int fontSize, int yPos, int pageHeight,
                                               int whitespaceAbove, List<String> customKeywords,
                                               int avgFont, boolean strict) {
        if (text == null || text.trim().isEmpty()) return false;
        if (HEADING_REGEX.matcher(text.toUpperCase()).matches()) return true;
        for (String kw : EXTRA_KEYWORDS) {
            if (text.equalsIgnoreCase(kw) || text.toLowerCase().startsWith(kw + " ")) return true;
        }
        if (customKeywords != null) {
            for (String kw : customKeywords) {
                if (text.toLowerCase().contains(kw.toLowerCase())) return true;
            }
        }
        if (fontSize >= avgFont + 2 && whitespaceAbove > 20) return true;
        if (!strict && fontSize >= avgFont && whitespaceAbove > 10) return true;
        return false;
    }
}