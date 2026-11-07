require_relative 'util'

DATA = { 'name' => 'ada', 'city' => 'london' }

def pick(hash, key)
  value = hash[key.to_sym]
  shout(value)
end

def run
  puts pick(DATA, 'name')
end

run
