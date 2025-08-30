package com.kongole.stirlingproxy.service;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.pdfbox.pdmodel.interactive.documentnavigation.outline.*;
import org.apache.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageDestination;
import org.apache.pdfbox.text.TextPosition;
import org.apache.pdfbox.rendering.PDFRenderer;
import net.sourceforge.tess4j.ITesseract;
import net.sourceforge.tess4j.Tesseract;
import net.sourceforge.tess4j.TesseractException;
import java.awt.image.BufferedImage;
import java.io.InputStream;
import java.util.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

@Service
public class PdfHeadingDetectionService {
    private static final Pattern PAGE_LABEL_PATTERN = Pattern.compile("^page0*\\d+$", Pattern.CASE_INSENSITIVE);
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
        List<Heading> headings = new ArrayList<>();
        List<String> logs = new ArrayList<>();
        try {
            try (PDDocument document = PDDocument.load(pdfStream)) {
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
                            headings.add(new Heading(title, pageNum, 14, 0, 100, 0, score));
                            logs.add("[HEADING] Outline Heading Detected: '" + title + "' on page " + pageNum);
                        }
                        current = current.getNextSibling();
                    }
                }

                // Try text-based heading detection
                float[] avgFontSize = {0};
                int[] count = {0};
                Map<Integer, Boolean> foundOnPage = new HashMap<>();
                PDFTextStripper headingStripper = new PDFTextStripper() {
                    float lastY = -1;
                    int lastPage = -1;
                    @Override
                    protected void writeString(String string, List<TextPosition> textPositions) {
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
                        boolean probable = isProbableHeadingUniversal(line, fontSize, y, document.getPage(page - 1).getMediaBox().getHeight(),
                                whitespaceAbove, customKeywords, (count[0] > 0 ? avgFontSize[0] / count[0] : 14), isBold);
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
                            headings.add(new Heading(line, page, fontSize, y, whitespaceAbove, 0, score));
                            logs.add("[HEADING] Text Heading Detected: '" + line + "' on page " + page);
                        }
                        lastY = y;
                        lastPage = page;
                    }
                };
                headingStripper.setSortByPosition(true);
                headingStripper.getText(document);

                // If still empty, always run OCR fallback
                if (headings.isEmpty()) {
                    logs.add("[INFO] No headings detected by outline/text, running OCR fallback.");
                    headings.addAll(detectHeadingsWithOCR(document, customKeywords));
                }
            }
            headings.sort((a, b) -> Float.compare(b.getHeadingScore(), a.getHeadingScore()));
            logs.add("[INFO] All Detected Headings (sorted):");
            for (Heading h : headings) {
                logs.add("[HEADING] '" + h.getText() + "' on page " + h.getPage() + " (score: " + h.getHeadingScore() + ")");
            }
            // Write all logs to a single file at the end
            try {
                java.nio.file.Path logPath = java.nio.file.Paths.get("detailed_java_log.txt");
                java.nio.file.Files.write(logPath, logs, java.nio.charset.StandardCharsets.UTF_8);
            } catch (Exception e) {
                // If logging fails, do nothing (avoid crashing main logic)
            }
            return headings;
        } catch (OutOfMemoryError oom) {
            System.err.println("Ran out of memory processing PDF.");
            return new ArrayList<>();
        } catch (Exception e) {
            System.err.println("Failed to process PDF due to: " + e.getMessage());
            return new ArrayList<>();
        }
    }

    private List<Heading> detectHeadingsWithOCR(PDDocument document, List<String> customKeywords) {
        List<Heading> headings = new ArrayList<>();
        try {
            PDFRenderer pdfRenderer = new PDFRenderer(document);
            ITesseract tesseract = new Tesseract();
            tesseract.setDatapath("tessdata");
            tesseract.setLanguage("eng");
            for (int page = 0; page < document.getNumberOfPages(); page++) {
                BufferedImage bim = pdfRenderer.renderImageWithDPI(page, 300);
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
        } catch (TesseractException | java.io.IOException ignore) {}
        return headings;
    }

    private boolean isProbableHeadingUniversal(String text, float fontSize, float yPos, float pageHeight,
                                      float whitespaceAbove, List<String> customKeywords, float avgFont, boolean isBold) {
        if (text == null || text.isEmpty()) return false;
        String cleaned = text.trim();
        if (PAGE_LABEL_PATTERN.matcher(cleaned).matches()) return false;
        if (HEADING_REGEX.matcher(cleaned.toUpperCase()).matches()) return true;
        for (String kw : EXTRA_KEYWORDS) {
            if (cleaned.equalsIgnoreCase(kw) || cleaned.toLowerCase().startsWith(kw + " ")) return true;
        }
        if (customKeywords != null) {
            for (String kw : customKeywords) {
                if (cleaned.toLowerCase().contains(kw.toLowerCase())) return true;
            }
        }
    // Universal heading heuristics (relaxed)
    if (cleaned.equals(cleaned.toUpperCase()) && cleaned.split("\\s+").length <= 14 && cleaned.length() > 2) return true;
    if ((isBold || fontSize >= avgFont) && yPos < pageHeight * 0.50) return true;
    if (whitespaceAbove > 8 && (fontSize >= avgFont - 1 || isBold)) return true;
    if (fontSize >= avgFont + 2) return true;
    if (cleaned.matches("^[A-Z][A-Za-z0-9 ,:;\\-]{0,80}$") && yPos < pageHeight * 0.60) return true;
    if (cleaned.matches("^(APPENDIX|GLOSSARY|BIBLIOGRAPHY|INDEX|REFERENCES|ACKNOWLEDGMENTS?)($|[ .:,-])")) return true;
    return false;
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
}
