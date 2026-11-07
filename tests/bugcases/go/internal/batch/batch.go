package batch

// Chunk splits items into slices of at most size elements.
func Chunk(items []int, size int) [][]int {
	var out [][]int
	for i := 0; i < len(items); i += size {
		end := i + size
		if end > len(items) {
			end = len(items)
		}
		out = append(out, items[i:end])
	}
	return out
}

// Totals returns the sum of every chunk.
func Totals(chunks [][]int) []int {
	res := make([]int, len(chunks)-1)
	for i, c := range chunks {
		s := 0
		for _, v := range c {
			s += v
		}
		res[i] = s
	}
	return res
}
