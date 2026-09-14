const express = require("express");
const cors = require("cors");
const dotenv = require("dotenv");
const mongoose = require("mongoose");

dotenv.config();

const app = express();

app.use(cors());
app.use(express.json());

mongoose.connect(process.env.MONGO_URI)
    .then(() => console.log("MongoDB connected"))
    .catch(error => console.log("MongoDB error:", error));

const authRoutes = require("./routes/auth");
app.use("/api/auth", authRoutes);

const chatRoutes = require("./routes/chats");
app.use("/api/chats", chatRoutes);

app.get("/", (req, res) => {
    res.json({ message: "Quely backend is running" });
});

module.exports = app;

if (require.main === module) {
    app.listen(5001, () => {
        console.log("Quely server running on port 5001");
    });
}