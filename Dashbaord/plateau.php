<?php
$servername = "localhost";
$username   = "root";
$password   = "";
$dbname     = "PEC"; 

// Create connection
$conn = new mysqli($servername, $username, $password, $dbname);

// Check connection
if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
}

// Get POST data
$plateau_number = isset($_POST['plateau_number']) ? intval($_POST['plateau_number']) : 0;
$duration       = isset($_POST['duration_seconds']) ? floatval($_POST['duration_seconds']) : 0;

// Insert query
$sql = "INSERT INTO plateau_monitor (plateau_number, duration_seconds) 
        VALUES ($plateau_number, $duration)";

if ($conn->query($sql) === TRUE) {
    echo "Record inserted successfully";
} else {
    echo "Error: " . $conn->error;
}

$conn->close();
?>
