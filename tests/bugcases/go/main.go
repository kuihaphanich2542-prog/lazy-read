package main

import (
	"fmt"

	"demo/internal/batch"
)

func run(items []int) []int {
	chunks := batch.Chunk(items, 2)
	return batch.Totals(chunks)
}

func main() {
	fmt.Println(run([]int{1, 2, 3, 4, 5}))
}
