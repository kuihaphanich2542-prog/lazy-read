package store

type Counter struct {
	hits map[string]int
	name string
}

// New builds a counter.
func New(name string) *Counter {
	return &Counter{name: name}
}

// Inc records one hit for key.
func (c *Counter) Inc(key string) {
	c.hits[key]++
}

func (c *Counter) Name() string { return c.name }
