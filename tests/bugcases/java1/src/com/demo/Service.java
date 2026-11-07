package com.demo;

public class Service {
    private final Repo repo = new Repo();

    public String shout(int id) {
        String name = repo.find(id);
        return name.toUpperCase();
    }

    public int total(int[] ids) {
        int n = 0;
        for (int id : ids) {
            n += shout(id).length();
        }
        return n;
    }
}
