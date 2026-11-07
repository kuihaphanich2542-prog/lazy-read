<?php
require __DIR__ . '/Calc.php';
function run() {
    $c = new Calc();
    return $c->ratio(10, 0);
}
echo run();
