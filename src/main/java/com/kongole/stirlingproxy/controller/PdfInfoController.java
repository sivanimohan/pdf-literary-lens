package com.kongole.stirlingproxy.controller;

import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;
import org.springframework.beans.factory.annotation.Autowired;
import com.kongole.stirlingproxy.service.PdfHeadingDetectionService;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.regex.Pattern;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;


@RestController
@RequestMapping("/")
public class PdfInfoController {

    @Autowired
    private PdfHeadingDetectionService pdfHeadingDetectionService;

    private static final Pattern CHAPTER_REGEX = Pattern.compile(
        "^(CHAPTER|SECTION|PART|UNIT)\\s+([0-9]+|[IVXLCDM]+)(\\s*[:\\-].*)?$",
        Pattern.CASE_INSENSITIVE
    );

    private static final String[] SPECIAL_KEYWORDS = {
        "prologue", "epilogue", "introduction", "preface", "foreword"
    };

    private static boolean isChapterHeading(
            PdfHeadingDetectionService.Heading heading,
            float avgFontSize,
            float pageHeight
    ) {
        if (heading == null || heading.getText() == null) return false;

        String text = heading.getText().trim();
        if (text.isEmpty()) return false;

        if (CHAPTER_REGEX.matcher(text.toUpperCase()).matches()) {
            return true;
        }

        String lower = text.toLowerCase();
        for (String kw : SPECIAL_KEYWORDS) {
            if (lower.equals(kw) || lower.startsWith(kw + " ")) {
                return true;
            }
        }

        if (text.equals(text.toUpperCase()) && text.split("\\s+").length <= 8) {
            return true;
        }

        try {
            if (heading.getFontSize() >= avgFontSize + 2) {
                if (heading.getYPosition() < pageHeight * 0.25) {
                    return true;
                }
            }
        } catch (Exception ignore) {}

        return false;
    }

    private static float computeAverageFontSize(List<PdfHeadingDetectionService.Heading> headings) {
        float total = 0;
        int count = 0;
        for (var h : headings) {
            try {
                total += h.getFontSize();
                count++;
            } catch (Exception ignore) {}
        }
        return count > 0 ? total / count : 0;
    }

    @PostMapping("/get/pdf-info/detect-headings")
    public ResponseEntity<?> detectHeadings(@RequestParam("file") MultipartFile file) {
        try {
            // 1. Local Java logic only, exclude level 0
            List<PdfHeadingDetectionService.Heading> headings =
                pdfHeadingDetectionService.detectHeadings(file.getInputStream(), null);

            float avgFont = computeAverageFontSize(headings);
            float pageHeight = 800;
            for (var h : headings) {
                if (h.getYPosition() > 0) {
                    pageHeight = Math.max(pageHeight, h.getYPosition() * 1.5f);
                }
            }

            List<java.util.Map<String, Object>> chapterList = new ArrayList<>();
            for (var heading : headings) {
                int level = heading.getFontSize() >= avgFont + 2 ? 1 : 0;
                if (level == 1 && isChapterHeading(heading, avgFont, pageHeight)) {
                    java.util.Map<String, Object> entry = new java.util.LinkedHashMap<>();
                    entry.put("title", heading.getText());
                    entry.put("pageNumber", heading.getPage());
                    entry.put("level", level);
                    chapterList.add(entry);
                }
            }

            // Write only Java logic result to result.json, exclude level 0
            ObjectMapper mapper = new ObjectMapper();
            mapper.writerWithDefaultPrettyPrinter().writeValue(new File("result.json"), chapterList);

            // Return only the filtered Java result
            return ResponseEntity.ok(chapterList);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body("Error: " + e.getMessage());
        }
    }

    @PostMapping("/get/pdf-info/detect-chapter-headings")
    public ResponseEntity<?> detectChapterHeadings(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "customKeywords", required = false) List<String> customKeywords
    ) {
        try {
            List<PdfHeadingDetectionService.Heading> headings =
                pdfHeadingDetectionService.detectHeadings(file.getInputStream(), customKeywords);

            float avgFont = computeAverageFontSize(headings);

            // Try to infer real page height from headings if available, else default to 800
            float pageHeight = 800;
            for (var h : headings) {
                if (h.getYPosition() > 0) {
                    pageHeight = Math.max(pageHeight, h.getYPosition() * 1.5f);
                }
            }

            List<Map<String, Object>> chapterHeadings = new ArrayList<>();
            for (var heading : headings) {
                if (isChapterHeading(heading, avgFont, pageHeight)) {
                    Map<String, Object> entry = new java.util.LinkedHashMap<>();
                    entry.put("title", heading.getText());
                    entry.put("pageNumber", heading.getPage());
                    entry.put("level",  heading.getFontSize() >= avgFont + 2 ? 1 : 0);
                    chapterHeadings.add(entry);
                }
            }

            // Return chapter headings as JSON in the required format
            return ResponseEntity.ok(chapterHeadings);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body("Error: " + e.getMessage());
        }
    }
}