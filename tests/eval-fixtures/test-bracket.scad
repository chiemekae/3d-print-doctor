// Eval fixture for 3d-print-doctor: a shelf bracket that needs supports both on the part and on the bed.
difference() {
  union() {
    cube([50, 25, 4]);                       // base
    cube([8, 25, 20]);                       // thick wall: has sparse infill
    translate([0, 0, 16]) cube([40, 25, 4]); // shelf over the base: supports stand on the part
    translate([-15, 0, 16]) cube([15, 25, 4]); // shelf past the base: supports from the bed
  }
  translate([20, 10, 2]) cube([10, 5, 3]);    // notch under the shelf: support wedges into it
}
