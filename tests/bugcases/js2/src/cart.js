'use strict';
const { each } = require('libx');
class Cart {
  constructor(items) {
    this.items = items;
    this.total = 0;
  }
  addPrice(item) {
    this.total += item.price * this.taxRate(item);
  }
  taxRate(item) {
    return item.taxable ? 1.07 : 1;
  }
  sum() {
    // iterate with a callback
    each(this.items, this.addPrice);
    return this.total;
  }
}
module.exports = { Cart };
