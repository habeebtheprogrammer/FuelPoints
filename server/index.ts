import express from "express";
import cors from "cors";
import bcrypt from "bcrypt";
import path from "path";
import { fileURLToPath } from "url";
import { storage } from "./storage";
import { generateAccountNumber, generateLoyaltyId, upcMatchesAny } from "./utils";
import salesRoutes from "./routes/sales.js";
import loyaltyRoutes from "./routes/loyalty.js";
import punchCardRoutes from "./routes/punchcards.js";
import { db } from "./db.js";
import { sendWelcomeEmail, sendPasswordResetEmail } from "./email.js";
import crypto from "crypto";
import { loyaltyTransactions, loyaltyFailedLookups, passwordResetTokens, adminUsers, promotions, punchCardPromotions, itemGroups, itemGroupUpcs, pricebook, jobApplications } from "../shared/schema.js";
import { sql, eq, and, gt, desc } from "drizzle-orm";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const isProduction = process.env.NODE_ENV === "production";
const PORT = Number(process.env.PORT) || (isProduction ? 5000 : 3001);

app.use(cors());
app.use(express.json({ limit: "50mb" }));

app.use("/api/sales", salesRoutes);
app.use("/api/loyalty", loyaltyRoutes);
app.use("/api/punch-cards", punchCardRoutes);

// Geocoding endpoint for zip code to coordinates
const geocodeCache: { [zip: string]: { lat: number; lng: number } } = {};

app.get("/api/geocode/:zipCode", async (req, res) => {
  const { zipCode } = req.params;
  
  if (geocodeCache[zipCode]) {
    return res.json(geocodeCache[zipCode]);
  }
  
  const apiKey = process.env.GOOGLE_MAPS_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "Geocoding not configured" });
  }
  
  try {
    const response = await fetch(
      `https://maps.googleapis.com/maps/api/geocode/json?address=${zipCode}&key=${apiKey}`
    );
    const data = await response.json();
    
    if (data.results && data.results.length > 0) {
      const { lat, lng } = data.results[0].geometry.location;
      geocodeCache[zipCode] = { lat, lng };
      res.json({ lat, lng });
    } else {
      res.status(404).json({ error: "Zip code not found" });
    }
  } catch (error) {
    console.log("Geocoding error:", error);
    res.status(500).json({ error: "Geocoding failed" });
  }
});

// Admin login endpoint
app.post("/api/admin/login", async (req, res) => {
  try {
    const { username, password } = req.body;

    if (!username || !password) {
      return res.status(400).json({ error: "Username and password are required" });
    }

    const admins = await db.select().from(adminUsers).where(eq(adminUsers.email, username));
    
    if (admins.length === 0) {
      return res.status(401).json({ error: "Invalid username or password" });
    }

    const admin = admins[0];
    const passwordMatch = await bcrypt.compare(password, admin.password);

    if (!passwordMatch) {
      return res.status(401).json({ error: "Invalid username or password" });
    }

    const token = crypto.randomBytes(32).toString("hex");

    res.json({
      token,
      user: {
        id: admin.id,
        firstName: admin.firstName,
        lastName: admin.lastName,
        email: admin.email,
      },
    });
  } catch (error) {
    console.log("Admin login error:", error);
    res.status(500).json({ error: "Login failed" });
  }
});

// Verify admin token endpoint
app.get("/api/admin/verify", async (req, res) => {
  const token = req.headers.authorization?.replace("Bearer ", "");
  if (!token) {
    return res.status(401).json({ error: "No token provided" });
  }
  res.json({ valid: true });
});

// Serve static files from Vite build in production
if (isProduction) {
  const distPath = path.join(__dirname, "..", "dist");
  app.use(express.static(distPath));
}

app.post("/api/register", async (req, res) => {
  try {
    const { firstName, lastName, email, phone, dateOfBirth, password } =
      req.body;

    if (
      !firstName ||
      !lastName ||
      !email ||
      !phone ||
      !dateOfBirth ||
      !password
    ) {
      return res.status(400).json({ error: "All fields are required" });
    }

    const existingUser = await storage.getUserByEmail(email);
    if (existingUser) {
      return res.status(400).json({ error: "Email already registered" });
    }

    const accountNumber = generateAccountNumber();
    const loyaltyId = generateLoyaltyId(accountNumber);
    const hashedPassword = await bcrypt.hash(password, 10);

    const user = await storage.createUser({
      firstName,
      lastName,
      email,
      phone,
      dateOfBirth,
      password: hashedPassword,
      accountNumber,
      loyaltyId,
    });

    const { password: _, ...userWithoutPassword } = user;
    
    sendWelcomeEmail(email, firstName, loyaltyId);
    
    res.status(201).json(userWithoutPassword);
  } catch (error) {
    console.log("Registration error:", error);
    res.status(500).json({ error: "Failed to register user" });
  }
});

// Public customer signup (PIN for new users, password for legacy)
app.post("/api/public/signup", async (req, res) => {
  try {
    const { firstName, lastName, phone, dateOfBirth, email, password, pin, zipCode } = req.body;
    
    console.log("Signup attempt:", { firstName, lastName, phone, dateOfBirth, zipCode, pin, hasPin: !!pin, hasPassword: !!password });

    if (!firstName || !lastName || !phone || !dateOfBirth || !zipCode) {
      console.log("Missing required fields");

      return res
        .status(400)
        .json({
          error: "First name, last name, phone, date of birth, and zip code are required",
        });
    }

    // New users use PIN, legacy support for password
    if (!pin && !password) {
      console.log("No PIN or password provided");
      return res.status(400).json({ error: "4-digit PIN is required" });
    }

    // Validate PIN if provided (must be exactly 4 digits)
    if (pin && (pin.length !== 4 || !/^\d{4}$/.test(pin))) {
      console.log("PIN validation failed:", pin);
      return res.status(400).json({ error: "PIN must be exactly 4 digits" });
    }

    // Validate password if provided (legacy support)
    if (password && password.length < 6) {
      console.log("Password too short");
      return res.status(400).json({ error: "Password must be at least 6 characters" });
    }

    // Validate phone number (must be 10 digits)
    const phoneDigits = phone.replace(/\D/g, "");
    if (phoneDigits.length !== 10) {
      console.log("Phone validation failed:", phoneDigits);
      return res.status(400).json({ error: "Phone number must be 10 digits" });
    }

    // Normalize phone to XXX-XXX-XXXX format for consistent storage
    const normalizedPhone = `${phoneDigits.slice(0, 3)}-${phoneDigits.slice(3, 6)}-${phoneDigits.slice(6)}`;

    // Check if phone number already exists
    const existingUser = await storage.getUserByPhone(normalizedPhone);
    if (existingUser) {
      console.log("Phone already registered:", normalizedPhone);
      return res.status(400).json({ error: "Phone number already registered" });
    }

    // Check if email already exists (only if provided)
    if (email) {
      const existingEmail = await storage.getUserByEmail(email);
      if (existingEmail) {
        return res.status(400).json({ error: "Email already registered" });
      }
    }

    const accountNumber = generateAccountNumber();
    const loyaltyId = generateLoyaltyId(accountNumber);
    
    // Hash password if provided (legacy), otherwise store PIN directly (4 digits only)
    const hashedPassword = password ? await bcrypt.hash(password, 10) : null;

    const user = await storage.createUser({
      firstName,
      lastName,
      email: email || null,
      phone: normalizedPhone,
      dateOfBirth,
      zipCode,
      password: hashedPassword,
      pin: pin || null,
      accountNumber,
      loyaltyId,
    });

    if (email) {
      sendWelcomeEmail(email, firstName, loyaltyId);
    }
    
    res.status(201).json({
      success: true,
      message: "Welcome to Birdies Loyalty Program!",
      customer: {
        id: user.id,
        firstName: user.firstName,
        lastName: user.lastName,
        phone: user.phone,
        loyaltyId: user.loyaltyId,
        accountNumber: user.accountNumber,
      },
    });
  } catch (error) {
    console.log("Public signup error:", error);
    res
      .status(500)
      .json({ error: "Failed to create account. Please try again." });
  }
});

app.post("/api/login", async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: "Email and password are required" });
    }

    const user = await storage.getUserByEmail(email);
    if (!user) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    const passwordMatch = await bcrypt.compare(password, user.password);
    if (!passwordMatch) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    const { password: _, ...userWithoutPassword } = user;
    res.json(userWithoutPassword);
  } catch (error) {
    console.log("Login error:", error);
    res.status(500).json({ error: "Failed to login" });
  }
});

// Mobile app login - phone required, PIN or password for authentication
app.post("/api/mobile/login", async (req, res) => {
  try {
    const { phone, password, pin } = req.body;

    if (!phone) {
      return res.status(400).json({ error: "Phone number is required" });
    }

    const phoneDigits = phone.replace(/\D/g, "");
    if (phoneDigits.length !== 10) {
      return res.status(400).json({ error: "Invalid phone number" });
    }

    const normalizedPhone = `${phoneDigits.slice(0, 3)}-${phoneDigits.slice(3, 6)}-${phoneDigits.slice(6)}`;
    const user = await storage.getUserByPhone(normalizedPhone);

    if (!user) {
      return res.status(401).json({ error: "Account not found. Please sign up first." });
    }

    // Check authentication based on what the user has set
    if (user.pin) {
      // User has PIN set - verify PIN
      if (!pin) {
        return res.status(401).json({ error: "PIN is required" });
      }
      if (user.pin !== pin) {
        return res.status(401).json({ error: "Invalid PIN" });
      }
    } else if (user.password) {
      // User has password set (legacy) - verify password
      if (!password) {
        return res.status(401).json({ error: "Password is required" });
      }
      const passwordMatch = await bcrypt.compare(password, user.password);
      if (!passwordMatch) {
        return res.status(401).json({ error: "Invalid password" });
      }
    }
    // If user has neither PIN nor password, allow login (very old legacy user)

    const rewards = await storage.getUserRewards(user.id);
    
    res.json({
      success: true,
      customer: {
        id: user.id,
        firstName: user.firstName,
        lastName: user.lastName,
        phone: user.phone,
        email: user.email,
        dateOfBirth: user.dateOfBirth,
        loyaltyId: user.loyaltyId,
        accountNumber: user.accountNumber,
        pointsBalance: rewards?.points || 0,
      },
    });
  } catch (error) {
    console.log("Mobile login error:", error);
    res.status(500).json({ error: "Login failed. Please try again." });
  }
});

// Request password reset
app.post("/api/forgot-password", async (req, res) => {
  try {
    const { phone } = req.body;

    if (!phone) {
      return res.status(400).json({ error: "Phone number is required" });
    }

    const phoneDigits = phone.replace(/\D/g, "");
    if (phoneDigits.length !== 10) {
      return res.status(400).json({ error: "Invalid phone number" });
    }

    const normalizedPhone = `${phoneDigits.slice(0, 3)}-${phoneDigits.slice(3, 6)}-${phoneDigits.slice(6)}`;
    const user = await storage.getUserByPhone(normalizedPhone);

    if (!user) {
      return res.json({ success: true, message: "If an account exists with that phone number, a reset link will be sent to the associated email." });
    }

    if (!user.email) {
      return res.status(400).json({ error: "No email associated with this account. Please contact support." });
    }

    const token = crypto.randomBytes(32).toString("hex");
    const expiresAt = new Date(Date.now() + 60 * 60 * 1000);

    await db.insert(passwordResetTokens).values({
      userId: user.id,
      token: token,
      expiresAt: expiresAt,
    });

    const baseUrl = process.env.NODE_ENV === "production" 
      ? "https://birdiesloyalty.com" 
      : `http://localhost:${process.env.PORT || 5000}`;
    const resetLink = `${baseUrl}/reset-password?token=${token}`;

    await sendPasswordResetEmail(user.email, user.firstName, resetLink);

    res.json({ success: true, message: "If an account exists with that phone number, a reset link will be sent to the associated email." });
  } catch (error) {
    console.log("Forgot password error:", error);
    res.status(500).json({ error: "Failed to process request. Please try again." });
  }
});

// Reset password with token
app.post("/api/reset-password", async (req, res) => {
  try {
    const { token, password } = req.body;

    if (!token || !password) {
      return res.status(400).json({ error: "Token and password are required" });
    }

    if (password.length < 6) {
      return res.status(400).json({ error: "Password must be at least 6 characters" });
    }

    const result = await db.select().from(passwordResetTokens)
      .where(and(
        eq(passwordResetTokens.token, token),
        eq(passwordResetTokens.used, false),
        gt(passwordResetTokens.expiresAt, new Date())
      ));

    if (result.length === 0) {
      return res.status(400).json({ error: "Invalid or expired reset link. Please request a new one." });
    }

    const resetToken = result[0];
    const hashedPassword = await bcrypt.hash(password, 10);

    await db.execute(sql`UPDATE users SET password = ${hashedPassword} WHERE id = ${resetToken.userId}`);

    await db.update(passwordResetTokens)
      .set({ used: true })
      .where(eq(passwordResetTokens.id, resetToken.id));

    res.json({ success: true, message: "Password reset successfully! You can now sign in with your new password." });
  } catch (error) {
    console.log("Reset password error:", error);
    res.status(500).json({ error: "Failed to reset password. Please try again." });
  }
});

app.get("/api/user/:id", async (req, res) => {
  try {
    const userId = parseInt(req.params.id);
    const user = await storage.getUserById(userId);

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    const { password: _, ...userWithoutPassword } = user;
    res.json(userWithoutPassword);
  } catch (error) {
    console.log("Get user error:", error);
    res.status(500).json({ error: "Failed to get user" });
  }
});

app.get("/api/rewards/:userId", async (req, res) => {
  try {
    const userId = parseInt(req.params.userId);
    const rewards = await storage.getUserRewards(userId);
    const transactions = await storage.getUserTransactions(userId);

    res.json({
      points: rewards?.points || 0,
      history: transactions.map((t) => ({
        id: t.id.toString(),
        points: t.points,
        description: t.description,
        date: t.createdAt.toISOString(),
      })),
    });
  } catch (error) {
    console.log("Get rewards error:", error);
    res.status(500).json({ error: "Failed to get rewards" });
  }
});

app.post("/api/rewards/add", async (req, res) => {
  try {
    const { userId, points, description } = req.body;

    if (!userId || !points || !description) {
      return res
        .status(400)
        .json({ error: "userId, points, and description are required" });
    }

    await storage.addRewardPoints(userId, points, description);

    const rewards = await storage.getUserRewards(userId);
    const transactions = await storage.getUserTransactions(userId);

    res.json({
      points: rewards?.points || 0,
      history: transactions.map((t) => ({
        id: t.id.toString(),
        points: t.points,
        description: t.description,
        date: t.createdAt.toISOString(),
      })),
    });
  } catch (error) {
    console.log("Add rewards error:", error);
    res.status(500).json({ error: "Failed to add rewards" });
  }
});

// Admin API - Customers Management
app.get("/api/admin/customers", async (req, res) => {
  try {
    const customers = await storage.getAllUsers();
    const customersWithRewards = await Promise.all(
      customers.map(async (customer) => {
        const rewards = await storage.getUserRewards(customer.id);
        const { password, accountNumber, ...customerData } = customer;
        return {
          ...customerData,
          points: rewards?.points || 0,
        };
      }),
    );
    res.json(customersWithRewards);
  } catch (error) {
    console.log("Get all customers error:", error);
    res.status(500).json({ error: "Failed to get customers" });
  }
});

app.get("/api/admin/customers/:id/transactions", async (req, res) => {
  try {
    const customerId = parseInt(req.params.id);

    if (isNaN(customerId)) {
      return res.status(400).json({ error: "Invalid customer ID" });
    }

    const customer = await storage.getUserById(customerId);
    if (!customer) {
      return res.status(404).json({ error: "Customer not found" });
    }

    const transactions = await storage.getUserTransactions(customerId);
    res.json(transactions);
  } catch (error) {
    console.log("Get customer transactions error:", error);
    res.status(500).json({ error: "Failed to get customer transactions" });
  }
});

// Admin API - Admin Users Management
app.get("/api/admin/users", async (req, res) => {
  try {
    const adminUsers = await storage.getAllAdminUsers();
    const adminsWithoutPasswords = adminUsers.map(
      ({ password, ...admin }) => admin,
    );
    res.json(adminsWithoutPasswords);
  } catch (error) {
    console.log("Get all admin users error:", error);
    res.status(500).json({ error: "Failed to get admin users" });
  }
});

app.post("/api/admin/users", async (req, res) => {
  try {
    const { firstName, lastName, email, phone, password } = req.body;

    if (!firstName || !lastName || !email || !phone || !password) {
      return res.status(400).json({ error: "All fields are required" });
    }

    const existingAdmin = await storage.getAdminByEmail(email);
    if (existingAdmin) {
      return res.status(400).json({ error: "Email already registered" });
    }

    const hashedPassword = await bcrypt.hash(password, 10);

    const admin = await storage.createAdminUser({
      firstName,
      lastName,
      email,
      phone,
      password: hashedPassword,
    });

    const { password: _, ...adminWithoutPassword } = admin;
    res.status(201).json(adminWithoutPassword);
  } catch (error) {
    console.log("Create admin user error:", error);
    res.status(500).json({ error: "Failed to create admin user" });
  }
});

app.put("/api/admin/users/:id", async (req, res) => {
  try {
    const adminId = parseInt(req.params.id);
    const { firstName, lastName, email, phone, password } = req.body;

    const updates: any = {};
    if (firstName) updates.firstName = firstName;
    if (lastName) updates.lastName = lastName;
    if (email) updates.email = email;
    if (phone) updates.phone = phone;
    if (password) {
      updates.password = await bcrypt.hash(password, 10);
    }

    const updatedAdmin = await storage.updateAdminUser(adminId, updates);

    if (!updatedAdmin) {
      return res.status(404).json({ error: "Admin user not found" });
    }

    const { password: _, ...adminWithoutPassword } = updatedAdmin;
    res.json(adminWithoutPassword);
  } catch (error) {
    console.log("Update admin user error:", error);
    res.status(500).json({ error: "Failed to update admin user" });
  }
});

// Admin API - Locations Management
app.get("/api/admin/locations", async (req, res) => {
  try {
    const locations = await storage.getAllLocations();
    res.json(locations);
  } catch (error) {
    console.log("Get all locations error:", error);
    res.status(500).json({ error: "Failed to get locations" });
  }
});

app.post("/api/admin/locations", async (req, res) => {
  try {
    const {
      locationName,
      pdiStoreNumber,
      posId,
      address1,
      address2,
      city,
      state,
      zipCode,
      posType,
    } = req.body;

    if (
      !locationName ||
      !pdiStoreNumber ||
      !address1 ||
      !city ||
      !state ||
      !zipCode ||
      !posType
    ) {
      return res
        .status(400)
        .json({
          error:
            "Location name, PDI store number, address 1, city, state, zip code, and POS type are required",
        });
    }

    const location = await storage.createLocation({
      locationName,
      pdiStoreNumber,
      posId: posId || null,
      address1,
      address2: address2 || null,
      city,
      state,
      zipCode,
      posType,
    });

    res.status(201).json(location);
  } catch (error) {
    console.log("Create location error:", error);
    res.status(500).json({ error: "Failed to create location" });
  }
});

app.put("/api/admin/locations/:id", async (req, res) => {
  try {
    const locationId = parseInt(req.params.id);
    const {
      locationName,
      pdiStoreNumber,
      posId,
      address1,
      address2,
      city,
      state,
      zipCode,
      posType,
    } = req.body;

    const updates: any = {};
    if (locationName) updates.locationName = locationName;
    if (pdiStoreNumber) updates.pdiStoreNumber = pdiStoreNumber;
    if (posId !== undefined) updates.posId = posId;
    if (address1) updates.address1 = address1;
    if (address2 !== undefined) updates.address2 = address2;
    if (city) updates.city = city;
    if (state) updates.state = state;
    if (zipCode) updates.zipCode = zipCode;
    if (posType) updates.posType = posType;

    const updatedLocation = await storage.updateLocation(locationId, updates);

    if (!updatedLocation) {
      return res.status(404).json({ error: "Location not found" });
    }

    res.json(updatedLocation);
  } catch (error) {
    console.log("Update location error:", error);
    res.status(500).json({ error: "Failed to update location" });
  }
});

app.delete("/api/admin/locations/:id", async (req, res) => {
  try {
    const locationId = parseInt(req.params.id);
    await storage.deleteLocation(locationId);
    res.status(204).send();
  } catch (error) {
    console.log("Delete location error:", error);
    res.status(500).json({ error: "Failed to delete location" });
  }
});

// Admin API - Item Groups Management
app.get("/api/admin/item-groups", async (req, res) => {
  try {
    const itemGroups = await storage.getAllItemGroups();
    res.json(itemGroups);
  } catch (error) {
    console.log("Get all item groups error:", error);
    res.status(500).json({ error: "Failed to get item groups" });
  }
});

app.get("/api/admin/item-groups/:id", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const itemGroup = await storage.getItemGroupById(itemGroupId);

    if (!itemGroup) {
      return res.status(404).json({ error: "Item group not found" });
    }

    res.json(itemGroup);
  } catch (error) {
    console.log("Get item group error:", error);
    res.status(500).json({ error: "Failed to get item group" });
  }
});

app.post("/api/admin/item-groups", async (req, res) => {
  try {
    const { name, description } = req.body;

    if (!name) {
      return res.status(400).json({ error: "Item group name is required" });
    }

    const itemGroup = await storage.createItemGroup({
      name,
      description: description || null,
    });

    res.status(201).json(itemGroup);
  } catch (error: any) {
    console.log("Create item group error:", error);
    if (error.message?.includes("already exists")) {
      return res
        .status(400)
        .json({ error: "Item group with this name already exists" });
    }
    res.status(500).json({ error: "Failed to create item group" });
  }
});

app.put("/api/admin/item-groups/:id", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const { name, description } = req.body;

    const updates: any = {};
    if (name) updates.name = name;
    if (description !== undefined) updates.description = description;

    const updatedItemGroup = await storage.updateItemGroup(
      itemGroupId,
      updates,
    );

    if (!updatedItemGroup) {
      return res.status(404).json({ error: "Item group not found" });
    }

    res.json(updatedItemGroup);
  } catch (error: any) {
    console.log("Update item group error:", error);
    if (error.message?.includes("already exists")) {
      return res
        .status(400)
        .json({ error: "Item group with this name already exists" });
    }
    res.status(500).json({ error: "Failed to update item group" });
  }
});

app.delete("/api/admin/item-groups/:id", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);

    // Check if item group has promotions
    const promotions = await storage.getAllPromotions();
    const hasPromotions = promotions.some((p) => p.itemGroupId === itemGroupId);

    if (hasPromotions) {
      return res.status(400).json({
        error:
          "Cannot delete item group. It has promotions attached. Please delete the promotions first.",
      });
    }

    await storage.deleteItemGroup(itemGroupId);
    res.status(204).send();
  } catch (error) {
    console.log("Delete item group error:", error);
    res.status(500).json({ error: "Failed to delete item group" });
  }
});

// Admin API - Item Group UPCs Management
app.get("/api/admin/item-groups/:id/upcs", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const upcs = await storage.getItemGroupUpcs(itemGroupId);
    res.json(upcs);
  } catch (error) {
    console.log("Get item group UPCs error:", error);
    res.status(500).json({ error: "Failed to get item group UPCs" });
  }
});

app.post("/api/admin/item-groups/:id/upcs", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const { upc } = req.body;

    if (!upc) {
      return res.status(400).json({ error: "UPC is required" });
    }

    const newUpc = await storage.addUpcToItemGroup({
      itemGroupId,
      upc,
    });

    res.status(201).json(newUpc);
  } catch (error: any) {
    console.log("Add UPC to item group error:", error);
    if (error.message?.includes("already exists")) {
      return res
        .status(400)
        .json({ error: "This item is already in the group" });
    }
    res.status(500).json({ error: "Failed to add UPC to item group" });
  }
});

app.delete("/api/admin/item-groups/:groupId/upcs/:upc", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.groupId);
    const upc = req.params.upc;

    await storage.deleteItemGroupUpcByCode(itemGroupId, upc);
    res.status(204).send();
  } catch (error) {
    console.log("Delete item group UPC by code error:", error);
    res.status(500).json({ error: "Failed to delete item from group" });
  }
});

app.delete("/api/admin/item-group-upcs/:id", async (req, res) => {
  try {
    const upcId = parseInt(req.params.id);
    await storage.deleteItemGroupUpc(upcId);
    res.status(204).send();
  } catch (error) {
    console.log("Delete item group UPC error:", error);
    res.status(500).json({ error: "Failed to delete item group UPC" });
  }
});

// Admin API - UPC Conflict Detection
app.get("/api/admin/upc-conflicts", async (req, res) => {
  try {
    const itemGroupId = parseInt(req.query.itemGroupId as string);
    const context = req.query.context as string; // 'promotion' or 'punchCard'
    const excludeId = req.query.excludeId ? parseInt(req.query.excludeId as string) : null;

    if (!itemGroupId) {
      return res.status(400).json({ error: "itemGroupId is required" });
    }

    // Get all UPCs in the selected item group
    const upcsInGroup = await db
      .select({ upc: itemGroupUpcs.upc })
      .from(itemGroupUpcs)
      .where(eq(itemGroupUpcs.itemGroupId, itemGroupId));

    if (upcsInGroup.length === 0) {
      return res.json({ conflicts: [], hasConflicts: false });
    }

    const upcList = upcsInGroup.map(u => u.upc);
    const conflicts: Array<{
      upc: string;
      description: string | null;
      usedIn: Array<{ type: string; id: number; name: string }>;
    }> = [];

    // Find which item groups contain these UPCs
    const upcItemGroupMap = await db
      .select({
        upc: itemGroupUpcs.upc,
        itemGroupId: itemGroupUpcs.itemGroupId,
        itemGroupName: itemGroups.name,
      })
      .from(itemGroupUpcs)
      .innerJoin(itemGroups, eq(itemGroupUpcs.itemGroupId, itemGroups.id))
      .where(sql`${itemGroupUpcs.upc} IN (${sql.join(upcList.map(u => sql`${u}`), sql`, `)})`);

    // Get all active promotions and punch cards
    const activePromotions = await db
      .select({
        id: promotions.id,
        name: promotions.name,
        itemGroupId: promotions.itemGroupId,
      })
      .from(promotions)
      .where(eq(promotions.isActive, true));

    const activePunchCards = await db
      .select({
        id: punchCardPromotions.id,
        name: punchCardPromotions.name,
        itemGroupId: punchCardPromotions.itemGroupId,
      })
      .from(punchCardPromotions)
      .where(eq(punchCardPromotions.isActive, true));

    // Get pricebook descriptions for UPCs
    const pricebookItems = await db
      .select({ upc: pricebook.upc, description: pricebook.description })
      .from(pricebook)
      .where(sql`${pricebook.upc} IN (${sql.join(upcList.map(u => sql`${u}`), sql`, `)})`);
    
    const upcDescriptions: Record<string, string> = {};
    pricebookItems.forEach(item => {
      upcDescriptions[item.upc] = item.description;
    });

    // Build a map of itemGroupId to promotions/punch cards
    const itemGroupToPrograms: Record<number, Array<{ type: string; id: number; name: string }>> = {};
    
    for (const promo of activePromotions) {
      if (context === 'promotion' && excludeId && promo.id === excludeId) continue;
      if (!itemGroupToPrograms[promo.itemGroupId]) {
        itemGroupToPrograms[promo.itemGroupId] = [];
      }
      itemGroupToPrograms[promo.itemGroupId].push({
        type: 'promotion',
        id: promo.id,
        name: promo.name || `Promotion #${promo.id}`,
      });
    }

    for (const card of activePunchCards) {
      if (context === 'punchCard' && excludeId && card.id === excludeId) continue;
      if (!itemGroupToPrograms[card.itemGroupId]) {
        itemGroupToPrograms[card.itemGroupId] = [];
      }
      itemGroupToPrograms[card.itemGroupId].push({
        type: 'punchCard',
        id: card.id,
        name: card.name,
      });
    }

    // Check each UPC for conflicts
    for (const upc of upcList) {
      const usedIn: Array<{ type: string; id: number; name: string }> = [];
      
      // Find all item groups that contain this UPC
      const itemGroupsWithUpc = upcItemGroupMap.filter(u => u.upc === upc);
      
      for (const ig of itemGroupsWithUpc) {
        // Skip the current item group
        if (ig.itemGroupId === itemGroupId) continue;
        
        // Check if this item group is used in any programs
        const programs = itemGroupToPrograms[ig.itemGroupId];
        if (programs) {
          usedIn.push(...programs);
        }
      }
      
      // Also check if the current item group is used in other programs
      const currentPrograms = itemGroupToPrograms[itemGroupId];
      if (currentPrograms) {
        usedIn.push(...currentPrograms);
      }

      if (usedIn.length > 0) {
        conflicts.push({
          upc,
          description: upcDescriptions[upc] || null,
          usedIn: [...new Map(usedIn.map(item => [`${item.type}-${item.id}`, item])).values()],
        });
      }
    }

    res.json({
      conflicts,
      hasConflicts: conflicts.length > 0,
      totalUpcsChecked: upcList.length,
      conflictingUpcs: conflicts.length,
    });
  } catch (error) {
    console.log("UPC conflict check error:", error);
    res.status(500).json({ error: "Failed to check UPC conflicts" });
  }
});

// Admin API - Promotions Management
app.get("/api/admin/promotions", async (req, res) => {
  try {
    const promotions = await storage.getAllPromotions();
    const promotionsWithLocations = await Promise.all(
      promotions.map(async (promo) => {
        const locations = await storage.getPromotionLocations(promo.id);
        return {
          ...promo,
          locationIds: locations.map((loc) => loc.locationId),
        };
      }),
    );
    res.json(promotionsWithLocations);
  } catch (error) {
    console.log("Get all promotions error:", error);
    res.status(500).json({ error: "Failed to get promotions" });
  }
});

app.get("/api/admin/promotions/:id", async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    const promotion = await storage.getPromotionById(promotionId);

    if (!promotion) {
      return res.status(404).json({ error: "Promotion not found" });
    }

    const locations = await storage.getPromotionLocations(promotionId);
    res.json({ ...promotion, locations });
  } catch (error) {
    console.log("Get promotion error:", error);
    res.status(500).json({ error: "Failed to get promotion" });
  }
});

app.post("/api/admin/promotions", async (req, res) => {
  try {
    const {
      name,
      itemGroupId,
      quantity,
      freeQuantity,
      discountType,
      price,
      amountOff,
      requiresLoyaltyId,
      isActive,
      startDate,
      endDate,
      locationIds,
    } = req.body;

    if (!itemGroupId || !quantity) {
      return res
        .status(400)
        .json({ error: "Item group and quantity are required" });
    }

    const type = discountType || "multipack";

    if (type === "multipack" && !price) {
      return res
        .status(400)
        .json({ error: "Price is required for multi-pack promotions" });
    }

    if (type === "amountoff" && !amountOff) {
      return res
        .status(400)
        .json({ error: "Amount off is required for amount-off promotions" });
    }

    if (type === "bxgy" && (!freeQuantity || freeQuantity < 1)) {
      return res
        .status(400)
        .json({
          error: "Free quantity is required for Buy X Get Y Free promotions",
        });
    }

    const promotion = await storage.createPromotion({
      name: name || null,
      itemGroupId,
      quantity,
      freeQuantity: type === "bxgy" ? freeQuantity : null,
      discountType: type,
      price: price ? price.toString() : null,
      amountOff: amountOff ? amountOff.toString() : null,
      requiresLoyaltyId: requiresLoyaltyId || false,
      isActive: isActive !== undefined ? isActive : true,
      startDate: startDate ? new Date(startDate) : null,
      endDate: endDate ? new Date(endDate) : null,
    });

    if (locationIds && locationIds.length > 0) {
      for (const locationId of locationIds) {
        await storage.addLocationToPromotion({
          promotionId: promotion.id,
          locationId,
        });
      }
    }

    res.status(201).json(promotion);
  } catch (error) {
    console.log("Create promotion error:", error);
    res.status(500).json({ error: "Failed to create promotion" });
  }
});

app.put("/api/admin/promotions/:id", async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    const {
      name,
      itemGroupId,
      quantity,
      freeQuantity,
      discountType,
      price,
      amountOff,
      requiresLoyaltyId,
      isActive,
      startDate,
      endDate,
      locationIds,
    } = req.body;

    const updates: any = {};
    if (name !== undefined) updates.name = name || null;
    if (itemGroupId !== undefined) updates.itemGroupId = itemGroupId;
    if (quantity !== undefined) updates.quantity = quantity;
    if (freeQuantity !== undefined) updates.freeQuantity = freeQuantity;
    if (discountType !== undefined) updates.discountType = discountType;
    if (price !== undefined) updates.price = price ? price.toString() : null;
    if (amountOff !== undefined)
      updates.amountOff = amountOff ? amountOff.toString() : null;
    if (requiresLoyaltyId !== undefined)
      updates.requiresLoyaltyId = requiresLoyaltyId;
    if (isActive !== undefined) updates.isActive = isActive;
    if (startDate !== undefined)
      updates.startDate = startDate ? new Date(startDate) : null;
    if (endDate !== undefined)
      updates.endDate = endDate ? new Date(endDate) : null;

    if (locationIds !== undefined) {
      await storage.deleteAllPromotionLocations(promotionId);
      if (locationIds.length > 0) {
        for (const locationId of locationIds) {
          await storage.addLocationToPromotion({
            promotionId,
            locationId,
          });
        }
      }
    }

    const updatedPromotion = await storage.updatePromotion(
      promotionId,
      updates,
    );

    if (!updatedPromotion) {
      return res.status(404).json({ error: "Promotion not found" });
    }

    res.json(updatedPromotion);
  } catch (error) {
    console.log("Update promotion error:", error);
    res.status(500).json({ error: "Failed to update promotion" });
  }
});

app.delete("/api/admin/promotions/:id", async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    await storage.deletePromotion(promotionId);
    res.status(204).send();
  } catch (error) {
    console.log("Delete promotion error:", error);
    res.status(500).json({ error: "Failed to delete promotion" });
  }
});

app.get("/api/admin/pricebook/search", async (req, res) => {
  try {
    const query = req.query.q as string;

    if (!query || query.length < 2) {
      return res.json([]);
    }

    const results = await storage.searchPricebook(query);
    res.json(results);
  } catch (error) {
    console.log("Search pricebook error:", error);
    res.status(500).json({ error: "Failed to search pricebook" });
  }
});

app.post("/api/admin/pricebook", async (req, res) => {
  try {
    const { upc, description } = req.body;

    if (!upc || !description) {
      return res
        .status(400)
        .json({ error: "UPC and description are required" });
    }

    // Accept any UPC length - just validate it's not empty
    if (!upc.trim()) {
      return res.status(400).json({ error: "UPC cannot be empty" });
    }

    const newItem = await storage.createPricebookItem({
      upc: upc.trim(),
      description,
    });
    res.status(201).json(newItem);
  } catch (error: any) {
    console.log("Create pricebook item error:", error);
    if (
      error.message?.includes("duplicate") ||
      error.message?.includes("unique")
    ) {
      return res.status(400).json({ error: "UPC already exists" });
    }
    res.status(500).json({ error: "Failed to create pricebook item" });
  }
});

// POS API - Heartbeat & Presence Tracking
app.post("/api/pos/heartbeat", async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(
    `[${timestamp}] 💓 Heartbeat from Store ${req.body.pdiStoreNumber || "Unknown"}`,
  );

  try {
    const {
      pdiStoreNumber,
      posId,
      posType,
      posIpAddress,
      edgeIpAddress,
      edgeVersion,
    } = req.body;

    if (!pdiStoreNumber || !posType) {
      return res
        .status(400)
        .json({ error: "PDI store number and POS type are required" });
    }

    await storage.upsertPosPresence({
      pdiStoreNumber,
      posId,
      posType,
      posIpAddress,
      edgeIpAddress,
      edgeVersion,
    });

    res.json({ success: true, message: "Heartbeat received" });
  } catch (error) {
    console.log("POS heartbeat error:", error);
    res.status(500).json({ error: "Failed to process heartbeat" });
  }
});

app.get("/api/pos/presence", async (req, res) => {
  try {
    const presenceRecords = await storage.getAllPosPresence();
    res.json(presenceRecords);
  } catch (error) {
    console.log("Get POS presence error:", error);
    res.status(500).json({ error: "Failed to get POS presence" });
  }
});

// POS Loyalty Integration API
app.post("/api/pos/customer-lookup", async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`\n[${timestamp}] 📞 POS Customer Lookup Request:`);
  console.log("  Body:", JSON.stringify(req.body, null, 2));

  try {
    const { loyaltyId, phone, pdiStoreNumber } = req.body;

    if (!loyaltyId && !phone) {
      console.log(`  ❌ Missing both loyaltyId and phone`);
      return res
        .status(400)
        .json({ error: "Either loyaltyId or phone is required" });
    }

    let user;
    let inputType = "";
    let inputValue = "";

    if (loyaltyId) {
      console.log(`  🔍 Looking up by loyalty ID: ${loyaltyId}`);
      inputType = "barcode";
      inputValue = loyaltyId;
      user = await storage.getUserByLoyaltyId(loyaltyId);
    } else if (phone) {
      console.log(`  🔍 Looking up by phone: ${phone}`);
      inputType = "phone";
      inputValue = phone;
      user = await storage.getUserByPhone(phone);
    }

    if (!user) {
      console.log(`  ❌ Customer not found`);

      // Log the failed lookup
      try {
        await db.insert(loyaltyFailedLookups).values({
          lookupDate: new Date(),
          pdiStoreNumber: pdiStoreNumber || "UNKNOWN",
          inputType,
          inputValue,
          errorReason: "Not Found",
        });
        console.log(`  📝 Failed lookup logged to database`);
      } catch (logError) {
        console.log("  ⚠️ Failed to log failed lookup:", logError);
      }

      return res.status(404).json({ error: "Customer not found" });
    }

    const rewards = await storage.getUserRewards(user.id);
    const response = {
      customerId: user.id,
      firstName: user.firstName,
      lastName: user.lastName,
      loyaltyId: user.loyaltyId,
      phone: user.phone,
      email: user.email,
      dateOfBirth: user.dateOfBirth,
      pointsBalance: rewards?.points || 0,
    };

    console.log(
      `  ✅ Customer found: ${user.firstName} ${user.lastName} (${rewards?.points || 0} pts)`,
    );
    res.json(response);
  } catch (error) {
    console.log("  ❌ Customer lookup error:", error);
    res.status(500).json({ error: "Failed to lookup customer" });
  }
});

app.post("/api/pos/evaluate-promotions", async (req, res) => {
  try {
    const { pdiStoreNumber, items } = req.body;

    if (!pdiStoreNumber || !items || !Array.isArray(items)) {
      return res
        .status(400)
        .json({ error: "pdiStoreNumber and items array are required" });
    }

    const location = await storage.getLocationByPdiStoreNumber(pdiStoreNumber);
    if (!location) {
      return res.status(400).json({ error: "Location not found" });
    }

    const activePromotions = await storage.getActivePromotionsForLocation(
      location.id,
    );
    const itemPromotions: any[] = [];

    for (const item of items) {
      const upc = item.upc;
      const qty = item.quantity || 1;
      const originalPrice = parseFloat(item.price) || 0;

      for (const promo of activePromotions) {
        const upcs = await storage.getItemGroupUpcs(promo.itemGroupId);
        const upcList = upcs.map((u) => u.upc);

        if (upcMatchesAny(upc, upcList)) {
          const promoQty = promo.quantity;
          const freeQty = promo.freeQuantity || 0;
          const discountType = promo.discountType || "multipack";

          // For BXGY, total items per bundle is buy + free
          const totalItemsPerBundle =
            discountType === "bxgy" ? promoQty + freeQty : promoQty;
          const bundleCount = Math.floor(qty / totalItemsPerBundle);

          if (bundleCount > 0) {
            let totalDiscount = 0;
            let totalPromoPrice = 0;
            let totalRegularPrice = 0;
            let description = "";

            if (discountType === "amountoff") {
              // Amount Off: Split discount evenly across bundle
              const amountOff = parseFloat(promo.amountOff?.toString() || "0");
              totalDiscount = amountOff * bundleCount;
              const regularPricePerBundle = originalPrice * promoQty;
              totalRegularPrice = regularPricePerBundle * bundleCount;
              totalPromoPrice = totalRegularPrice - totalDiscount;
              description = `${bundleCount} x ($${amountOff.toFixed(2)} off ${promoQty})`;
            } else if (discountType === "bxgy") {
              // Buy X Get Y Free: Customer pays for promoQty items, gets freeQty items free
              // Example: Buy 2 Get 1 Free @ $3/each = Customer pays $6 for 3 items
              const paidPricePerBundle = originalPrice * promoQty;
              const regularPricePerBundle = originalPrice * totalItemsPerBundle;
              const discountPerBundle = originalPrice * freeQty;

              totalRegularPrice = regularPricePerBundle * bundleCount;
              totalPromoPrice = paidPricePerBundle * bundleCount;
              totalDiscount = discountPerBundle * bundleCount;
              description = `${bundleCount} x (Buy ${promoQty} Get ${freeQty} Free)`;
            } else {
              // Multi-pack: Set new price for bundle
              const promoPrice = parseFloat(promo.price?.toString() || "0");
              const regularPricePerBundle = originalPrice * promoQty;
              const discountPerBundle = regularPricePerBundle - promoPrice;
              totalRegularPrice = regularPricePerBundle * bundleCount;
              totalPromoPrice = promoPrice * bundleCount;
              totalDiscount = discountPerBundle * bundleCount;
              description = `${bundleCount} x (${promoQty} for $${promoPrice.toFixed(2)})`;
            }

            if (totalDiscount > 0) {
              itemPromotions.push({
                upc,
                promotionId: promo.id,
                name: promo.name,
                itemGroupName: promo.itemGroupName,
                discountType,
                quantity: totalItemsPerBundle,
                bundleCount,
                promoPrice: totalPromoPrice.toFixed(2),
                regularPrice: totalRegularPrice.toFixed(2),
                discount: totalDiscount.toFixed(2),
                description,
              });
            }
          }
        }
      }
    }

    res.json({ promotions: itemPromotions });
  } catch (error) {
    console.log("Evaluate promotions error:", error);
    res.status(500).json({ error: "Failed to evaluate promotions" });
  }
});

app.post("/api/pos/calculate-redemption", async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`\n[${timestamp}] 💰 POS Calculate Redemption Request:`);
  console.log("  Body:", JSON.stringify(req.body, null, 2));

  try {
    const { customerId, eligibleSubtotal, lineItems } = req.body;

    if (!customerId || eligibleSubtotal === undefined) {
      console.log(`  ❌ Missing required fields`);
      return res
        .status(400)
        .json({ error: "customerId and eligibleSubtotal are required" });
    }

    // Log product line items
    if (lineItems && lineItems.length > 0) {
      console.log(`\n  🛒 TRANSACTION ITEMS (${lineItems.length} items):`);
      lineItems.forEach((item: any, idx: number) => {
        const amount =
          typeof item.amount === "number"
            ? item.amount
            : parseFloat(item.amount) || 0;
        console.log(`     ${idx + 1}. UPC: ${item.upc || "N/A"}`);
        console.log(`        Desc: ${item.description || "N/A"}`);
        console.log(
          `        Qty: ${item.quantity || 1}, Amount: $${amount.toFixed(2)}`,
        );
      });
      console.log("");
    }

    const rewards = await storage.getUserRewards(customerId);
    const pointsBalance = rewards?.points || 0;

    const subtotal = parseFloat(eligibleSubtotal.toString());

    // Redemption based ONLY on points balance (100 points = $1, max $10)
    const maxByPoints = Math.floor(pointsBalance / 100);
    const redeemDollars = Math.min(maxByPoints, 10);
    const pointsToUse = redeemDollars * 100;

    console.log(
      `  📊 Calculation: subtotal=$${subtotal}, points=${pointsBalance}, redemption=$${redeemDollars}`,
    );

    res.json({
      pointsBalance,
      eligibleSubtotal: subtotal.toFixed(2),
      maxRedemptionByPoints: maxByPoints,
      recommendedRedemption: redeemDollars,
      pointsToRedeem: pointsToUse,
      newBalance: pointsBalance - pointsToUse,
    });
  } catch (error) {
    console.log("Calculate redemption error:", error);
    res.status(500).json({ error: "Failed to calculate redemption" });
  }
});

app.post("/api/pos/finalize-transaction", async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`\n[${timestamp}] 🏁 POS Finalize Transaction:`);
  console.log("  Body:", JSON.stringify(req.body, null, 2));

  try {
    const {
      customerId,
      eligibleSubtotal,
      pointsRedeemed,
      transactionId,
      pdiStoreNumber,
      lineItems,
      promotions,
      promotionDiscount,
    } = req.body;

    if (!customerId || eligibleSubtotal === undefined) {
      return res
        .status(400)
        .json({ error: "customerId and eligibleSubtotal are required" });
    }

    const subtotal = parseFloat(eligibleSubtotal.toString());
    const pointsEarned = Math.floor(subtotal * 5);
    const pointsUsed = parseInt(pointsRedeemed || "0");
    const promoDiscount = parseFloat(promotionDiscount || "0");
    const pointsDiscount = pointsUsed / 100;
    const totalDiscount = promoDiscount + pointsDiscount;
    const netAmount = subtotal - totalDiscount;

    // Get current points before transaction
    const rewardsBefore = await storage.getUserRewards(customerId);
    const pointsBefore = rewardsBefore?.points || 0;

    if (pointsUsed > 0) {
      await storage.addRewardPoints(
        customerId,
        -pointsUsed,
        `Points Redeemed - Transaction ${transactionId || "N/A"}`,
      );
    }

    if (pointsEarned > 0) {
      await storage.addRewardPoints(
        customerId,
        pointsEarned,
        `Purchase - Transaction ${transactionId || "N/A"}`,
      );
    }

    const rewardsAfter = await storage.getUserRewards(customerId);
    const pointsAfter = rewardsAfter?.points || 0;

    // Get customer info for denormalization
    const customer = await storage.getUserById(customerId);
    const customerName = customer
      ? `${customer.firstName} ${customer.lastName}`
      : "Unknown";
    const loyaltyId = customer?.loyaltyId || null;

    // Build promotion info
    const promoUsed = promotions && promotions.length > 0;
    const promoCount = promotions?.length || 0;
    const promoNames =
      promotions
        ?.map((p: any) => p.name || p.itemGroupName || "Unknown")
        .join(", ") || null;
    const promoDetails = promotions ? JSON.stringify(promotions) : null;
    const lineItemsJson = lineItems ? JSON.stringify(lineItems) : null;
    const itemCount = lineItems?.length || 0;

    // Save full transaction to loyalty_transactions table
    try {
      await db.insert(loyaltyTransactions).values({
        transactionId: transactionId || `POS-${Date.now()}`,
        transactionDate: new Date(),
        pdiStoreNumber: pdiStoreNumber || "UNKNOWN",
        customerId,
        customerName,
        loyaltyId,
        subtotal: subtotal.toString(),
        promotionDiscount: promoDiscount.toString(),
        pointsDiscount: pointsDiscount.toString(),
        totalDiscount: totalDiscount.toString(),
        netAmount: netAmount.toString(),
        pointsBefore,
        pointsEarned,
        pointsRedeemed: pointsUsed,
        pointsAfter,
        promotionUsed: promoUsed,
        promotionCount: promoCount,
        promotionNames: promoNames,
        promotionDetails: promoDetails,
        lineItems: lineItemsJson,
        itemCount,
      });
      console.log(`  📝 Transaction saved to loyalty_transactions`);
    } catch (saveError) {
      console.log("  ⚠️ Failed to save loyalty transaction:", saveError);
    }

    console.log(
      `  ✅ Transaction finalized: earned ${pointsEarned}, redeemed ${pointsUsed}, new balance ${pointsAfter}`,
    );

    res.json({
      success: true,
      pointsEarned,
      pointsRedeemed: pointsUsed,
      newBalance: pointsAfter,
      message: `Transaction complete. Earned ${pointsEarned} points, redeemed ${pointsUsed} points.`,
    });
  } catch (error) {
    console.log("Finalize transaction error:", error);
    res.status(500).json({ error: "Failed to finalize transaction" });
  }
});

// Mobile app: Get customer transactions
app.get("/api/transactions/customer/:customerId", async (req, res) => {
  try {
    const customerId = parseInt(req.params.customerId);
    if (isNaN(customerId)) {
      return res.status(400).json({ error: "Invalid customer ID" });
    }

    const { eq, desc } = await import("drizzle-orm");
    const transactions = await db
      .select({
        id: loyaltyTransactions.id,
        transactionId: loyaltyTransactions.transactionId,
        transactionDate: loyaltyTransactions.transactionDate,
        pdiStoreNumber: loyaltyTransactions.pdiStoreNumber,
        subtotal: loyaltyTransactions.subtotal,
        totalDiscount: loyaltyTransactions.totalDiscount,
        netAmount: loyaltyTransactions.netAmount,
        pointsEarned: loyaltyTransactions.pointsEarned,
        pointsRedeemed: loyaltyTransactions.pointsRedeemed,
        promotionUsed: loyaltyTransactions.promotionUsed,
        promotionNames: loyaltyTransactions.promotionNames,
      })
      .from(loyaltyTransactions)
      .where(eq(loyaltyTransactions.customerId, customerId))
      .orderBy(desc(loyaltyTransactions.transactionDate))
      .limit(50);

    res.json({
      transactions: transactions.map((t) => ({
        id: t.id,
        transactionId: t.transactionId,
        transactionDate: t.transactionDate,
        pdiStoreNumber: t.pdiStoreNumber,
        subtotal: parseFloat(t.subtotal || "0"),
        totalDiscount: parseFloat(t.totalDiscount || "0"),
        transactionTotal: parseFloat(t.netAmount || "0"),
        pointsEarned: t.pointsEarned || 0,
        pointsRedeemed: t.pointsRedeemed || 0,
        promotionUsed: t.promotionUsed,
        promotionNames: t.promotionNames,
      })),
    });
  } catch (error) {
    console.log("Get customer transactions error:", error);
    res.status(500).json({ error: "Failed to get transactions" });
  }
});

// Job Applications API
app.post("/api/job-applications", async (req, res) => {
  try {
    const {
      firstName,
      lastName,
      phone,
      email,
      isOver18,
      position,
      employmentType,
      availableShifts,
      startDate,
      previousExperience,
      retailExperience,
      authorizedToWork,
      canLiftAndStand,
      whyWorkHere,
      referralSource,
      storeLocation,
    } = req.body;

    if (!firstName || !lastName || !phone || !email) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    const [application] = await db
      .insert(jobApplications)
      .values({
        firstName,
        lastName,
        phone,
        email,
        isOver18: Boolean(isOver18),
        position,
        employmentType,
        availableShifts,
        startDate,
        previousExperience: previousExperience || null,
        retailExperience: Boolean(retailExperience),
        authorizedToWork: Boolean(authorizedToWork),
        canLiftAndStand: Boolean(canLiftAndStand),
        whyWorkHere: whyWorkHere || null,
        referralSource: referralSource || null,
        storeLocation: storeLocation || null,
        status: "new",
      })
      .returning();

    console.log(`New job application from ${firstName} ${lastName}`);
    res.json({ success: true, id: application.id });
  } catch (error) {
    console.log("Job application error:", error);
    res.status(500).json({ error: "Failed to submit application" });
  }
});

app.get("/api/job-applications", async (req, res) => {
  try {
    const applications = await db
      .select()
      .from(jobApplications)
      .orderBy(desc(jobApplications.createdAt));

    res.json(applications);
  } catch (error) {
    console.log("Get job applications error:", error);
    res.status(500).json({ error: "Failed to get applications" });
  }
});

app.patch("/api/job-applications/:id/status", async (req, res) => {
  try {
    const { id } = req.params;
    const { status } = req.body;

    const [updated] = await db
      .update(jobApplications)
      .set({ status })
      .where(eq(jobApplications.id, parseInt(id)))
      .returning();

    if (!updated) {
      return res.status(404).json({ error: "Application not found" });
    }

    res.json(updated);
  } catch (error) {
    console.log("Update job application error:", error);
    res.status(500).json({ error: "Failed to update application" });
  }
});

// Serve index.html for all other routes in production (SPA fallback)
if (isProduction) {
  app.use((req, res) => {
    res.sendFile(path.join(__dirname, "..", "dist", "index.html"));
  });
}

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Backend API server running on port ${PORT}`);
  console.log(`Environment: ${isProduction ? "production" : "development"}`);
});
