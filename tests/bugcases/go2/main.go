package main

import (
	"fmt"

	"demo2/store"
)

func record(c *store.Counter, keys []string) {
	for _, k := range keys {
		c.Inc(k)
	}
}

func main() {
	c := store.New("pages")
	record(c, []string{"a", "b"})
	fmt.Println(c.Name())
}
