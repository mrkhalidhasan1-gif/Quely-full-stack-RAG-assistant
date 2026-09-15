const express = require("express");
const cors = require("cors");
const dotenv = require("dotenv");
const mongoose = require("mongoose");

dotenv.config();

const app = express();

app.use(cors());
app.use(express.json());

mongoose.connect(process.env.MONGO_URI, { serverSelectionTimeoutMS: 10000 })
    .then(() => console.log("MongoDB connected"))
    .catch(error => {
        console.error("MongoDB error:", error);
        if (error.reason?.servers) {
            for (const [host, server] of error.reason.servers) {
                console.error("MongoDB server:", host, server.error || "No detailed error");
            }
        }
    });

app.use(async (req, res, next) => {
    try {
        await mongoose.connection.asPromise();
        next();
    } catch (error) {
        console.error("MongoDB request connection error:", error);
        res.status(503).json({ message: "Database temporarily unavailable." });
    }
});

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