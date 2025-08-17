package com.kongole.stirlingproxy.dto;

public class BookmarkInfo {
    private String title;
    private int pageNumber;
    private int level;

    public BookmarkInfo(String title, int pageNumber, int level) {
        this.title = title;
        this.pageNumber = pageNumber;
        this.level = level;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public int getPageNumber() {
        return pageNumber;
    }

    public void setPageNumber(int pageNumber) {
        this.pageNumber = pageNumber;
    }

    public int getLevel() {
        return level;
    }

    public void setLevel(int level) {
        this.level = level;
    }
}
