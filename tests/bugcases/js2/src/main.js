'use strict';
const { Cart } = require('./cart');
const cart = new Cart([{ price: 10, taxable: true }, { price: 5 }]);
console.log(cart.sum());
