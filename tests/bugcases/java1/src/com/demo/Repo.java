package com.demo;

import java.util.HashMap;
import java.util.Map;

public class Repo {
    private final Map<Integer, String> names = new HashMap<>();

    public Repo() {
        names.put(1, "ada");
        names.put(2, "alan");
    }

    public String find(int id) {
        return names.get(id);
    }
}
