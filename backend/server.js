const express = require("express");
const cors = require("cors");
const dotenv = require("dotenv");
const mongoose = require("mongoose");

dotenv.config();

const app = express();

app.use(cors());
app.use(express.json());


// MongoDB connection
mongoose.connect(process.env.MONGO_URI)
    .then(() => console.log("MongoDB connected"))
    .catch((error) => console.log("MongoDB error:", error));


// Authentication routes
const authRoutes = require("./routes/auth");
app.use("/api/auth", authRoutes);

const documentRoutes = require("./routes/documents");
app.use("/api/documents", documentRoutes);

const chatRoutes = require("./routes/chats");
app.use("/api/chats", chatRoutes);

// Test route
app.get("/", (req, res) => {
    res.json({
        message: "Quely backend is running"
    });
});


const PORT = 5001;

app.listen(PORT, () => {
    console.log(`Quely server running on port ${PORT}`);
});