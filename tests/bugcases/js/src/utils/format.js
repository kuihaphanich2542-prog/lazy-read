'use strict';
const PAD = 2;
function pad(n) { return String(n).padStart(PAD, '0'); }
function formatDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function initials(name) {
  return name.split(' ').map((p) => p[0]).join('').toUpperCase();
}
function formatUser(user) {
  // Build the public view of a user record
  return {
    id: user.id,
    display: user.profile.name,
    initials: initials(user.profile.name),
    joined: formatDate(new Date(user.createdAt)),
  };
}
module.exports = { formatUser, formatDate, initials };
