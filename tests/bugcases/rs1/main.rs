fn parse_all(items: &[&str]) -> Vec<i32> {
    let mut out = Vec::new();
    for s in items {
        out.push(s.trim().parse::<i32>().unwrap());
    }
    out
}

fn main() {
    let v = parse_all(&["1", " 2 ", "x3"]);
    println!("{:?}", v);
}
