const { paginate } = require('./paginate');
console.log(paginate([1,2,3,4,5,6], 0, 3).rows);
