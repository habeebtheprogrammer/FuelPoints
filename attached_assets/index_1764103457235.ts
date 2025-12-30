import express from 'express';
import cors from 'cors';
import bcrypt from 'bcrypt';
import path from 'path';
import { fileURLToPath } from 'url';
import { storage } from './storage';
import { generateAccountNumber, generateLoyaltyId } from './utils';
import salesRoutes from './routes/sales.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const isProduction = process.env.NODE_ENV === 'production';
const PORT = Number(process.env.PORT) || (isProduction ? 5000 : 3001);

app.use(cors());
app.use(express.json({ limit: '50mb' }));

app.use('/api/sales', salesRoutes);

// Serve static files from Vite build in production
if (isProduction) {
  const distPath = path.join(__dirname, '..', 'dist');
  app.use(express.static(distPath));
}

app.post('/api/register', async (req, res) => {
  try {
    const { firstName, lastName, email, phone, dateOfBirth, password } = req.body;

    if (!firstName || !lastName || !email || !phone || !dateOfBirth || !password) {
      return res.status(400).json({ error: 'All fields are required' });
    }

    const existingUser = await storage.getUserByEmail(email);
    if (existingUser) {
      return res.status(400).json({ error: 'Email already registered' });
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
    res.status(201).json(userWithoutPassword);
  } catch (error) {
    console.log('Registration error:', error);
    res.status(500).json({ error: 'Failed to register user' });
  }
});

app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const user = await storage.getUserByEmail(email);
    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const passwordMatch = await bcrypt.compare(password, user.password);
    if (!passwordMatch) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const { password: _, ...userWithoutPassword } = user;
    res.json(userWithoutPassword);
  } catch (error) {
    console.log('Login error:', error);
    res.status(500).json({ error: 'Failed to login' });
  }
});

app.get('/api/user/:id', async (req, res) => {
  try {
    const userId = parseInt(req.params.id);
    const user = await storage.getUserById(userId);

    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    const { password: _, ...userWithoutPassword } = user;
    res.json(userWithoutPassword);
  } catch (error) {
    console.log('Get user error:', error);
    res.status(500).json({ error: 'Failed to get user' });
  }
});

app.get('/api/rewards/:userId', async (req, res) => {
  try {
    const userId = parseInt(req.params.userId);
    const rewards = await storage.getUserRewards(userId);
    const transactions = await storage.getUserTransactions(userId);

    res.json({
      points: rewards?.points || 0,
      history: transactions.map(t => ({
        id: t.id.toString(),
        points: t.points,
        description: t.description,
        date: t.createdAt.toISOString(),
      })),
    });
  } catch (error) {
    console.log('Get rewards error:', error);
    res.status(500).json({ error: 'Failed to get rewards' });
  }
});

app.post('/api/rewards/add', async (req, res) => {
  try {
    const { userId, points, description } = req.body;

    if (!userId || !points || !description) {
      return res.status(400).json({ error: 'userId, points, and description are required' });
    }

    await storage.addRewardPoints(userId, points, description);
    
    const rewards = await storage.getUserRewards(userId);
    const transactions = await storage.getUserTransactions(userId);

    res.json({
      points: rewards?.points || 0,
      history: transactions.map(t => ({
        id: t.id.toString(),
        points: t.points,
        description: t.description,
        date: t.createdAt.toISOString(),
      })),
    });
  } catch (error) {
    console.log('Add rewards error:', error);
    res.status(500).json({ error: 'Failed to add rewards' });
  }
});

// Admin API - Customers Management
app.get('/api/admin/customers', async (req, res) => {
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
      })
    );
    res.json(customersWithRewards);
  } catch (error) {
    console.log('Get all customers error:', error);
    res.status(500).json({ error: 'Failed to get customers' });
  }
});

app.get('/api/admin/customers/:id/transactions', async (req, res) => {
  try {
    const customerId = parseInt(req.params.id);
    
    if (isNaN(customerId)) {
      return res.status(400).json({ error: 'Invalid customer ID' });
    }
    
    const customer = await storage.getUserById(customerId);
    if (!customer) {
      return res.status(404).json({ error: 'Customer not found' });
    }
    
    const transactions = await storage.getUserTransactions(customerId);
    res.json(transactions);
  } catch (error) {
    console.log('Get customer transactions error:', error);
    res.status(500).json({ error: 'Failed to get customer transactions' });
  }
});

// Admin API - Admin Users Management
app.get('/api/admin/users', async (req, res) => {
  try {
    const adminUsers = await storage.getAllAdminUsers();
    const adminsWithoutPasswords = adminUsers.map(({ password, ...admin }) => admin);
    res.json(adminsWithoutPasswords);
  } catch (error) {
    console.log('Get all admin users error:', error);
    res.status(500).json({ error: 'Failed to get admin users' });
  }
});

app.post('/api/admin/users', async (req, res) => {
  try {
    const { firstName, lastName, email, phone, password } = req.body;

    if (!firstName || !lastName || !email || !phone || !password) {
      return res.status(400).json({ error: 'All fields are required' });
    }

    const existingAdmin = await storage.getAdminByEmail(email);
    if (existingAdmin) {
      return res.status(400).json({ error: 'Email already registered' });
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
    console.log('Create admin user error:', error);
    res.status(500).json({ error: 'Failed to create admin user' });
  }
});

app.put('/api/admin/users/:id', async (req, res) => {
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
      return res.status(404).json({ error: 'Admin user not found' });
    }

    const { password: _, ...adminWithoutPassword } = updatedAdmin;
    res.json(adminWithoutPassword);
  } catch (error) {
    console.log('Update admin user error:', error);
    res.status(500).json({ error: 'Failed to update admin user' });
  }
});

// Admin API - Locations Management
app.get('/api/admin/locations', async (req, res) => {
  try {
    const locations = await storage.getAllLocations();
    res.json(locations);
  } catch (error) {
    console.log('Get all locations error:', error);
    res.status(500).json({ error: 'Failed to get locations' });
  }
});

app.post('/api/admin/locations', async (req, res) => {
  try {
    const { locationName, pdiStoreNumber, posId, address1, address2, city, state, zipCode, posType } = req.body;

    if (!locationName || !pdiStoreNumber || !address1 || !city || !state || !zipCode || !posType) {
      return res.status(400).json({ error: 'Location name, PDI store number, address 1, city, state, zip code, and POS type are required' });
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
    console.log('Create location error:', error);
    res.status(500).json({ error: 'Failed to create location' });
  }
});

app.put('/api/admin/locations/:id', async (req, res) => {
  try {
    const locationId = parseInt(req.params.id);
    const { locationName, pdiStoreNumber, posId, address1, address2, city, state, zipCode, posType } = req.body;

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
      return res.status(404).json({ error: 'Location not found' });
    }

    res.json(updatedLocation);
  } catch (error) {
    console.log('Update location error:', error);
    res.status(500).json({ error: 'Failed to update location' });
  }
});

app.delete('/api/admin/locations/:id', async (req, res) => {
  try {
    const locationId = parseInt(req.params.id);
    await storage.deleteLocation(locationId);
    res.status(204).send();
  } catch (error) {
    console.log('Delete location error:', error);
    res.status(500).json({ error: 'Failed to delete location' });
  }
});

// Admin API - Item Groups Management
app.get('/api/admin/item-groups', async (req, res) => {
  try {
    const itemGroups = await storage.getAllItemGroups();
    res.json(itemGroups);
  } catch (error) {
    console.log('Get all item groups error:', error);
    res.status(500).json({ error: 'Failed to get item groups' });
  }
});

app.get('/api/admin/item-groups/:id', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const itemGroup = await storage.getItemGroupById(itemGroupId);
    
    if (!itemGroup) {
      return res.status(404).json({ error: 'Item group not found' });
    }

    res.json(itemGroup);
  } catch (error) {
    console.log('Get item group error:', error);
    res.status(500).json({ error: 'Failed to get item group' });
  }
});

app.post('/api/admin/item-groups', async (req, res) => {
  try {
    const { name, description } = req.body;

    if (!name) {
      return res.status(400).json({ error: 'Item group name is required' });
    }

    const itemGroup = await storage.createItemGroup({
      name,
      description: description || null,
    });

    res.status(201).json(itemGroup);
  } catch (error: any) {
    console.log('Create item group error:', error);
    if (error.message?.includes('already exists')) {
      return res.status(400).json({ error: 'Item group with this name already exists' });
    }
    res.status(500).json({ error: 'Failed to create item group' });
  }
});

app.put('/api/admin/item-groups/:id', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const { name, description } = req.body;

    const updates: any = {};
    if (name) updates.name = name;
    if (description !== undefined) updates.description = description;

    const updatedItemGroup = await storage.updateItemGroup(itemGroupId, updates);
    
    if (!updatedItemGroup) {
      return res.status(404).json({ error: 'Item group not found' });
    }

    res.json(updatedItemGroup);
  } catch (error: any) {
    console.log('Update item group error:', error);
    if (error.message?.includes('already exists')) {
      return res.status(400).json({ error: 'Item group with this name already exists' });
    }
    res.status(500).json({ error: 'Failed to update item group' });
  }
});

app.delete('/api/admin/item-groups/:id', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    
    // Check if item group has promotions
    const promotions = await storage.getAllPromotions();
    const hasPromotions = promotions.some(p => p.itemGroupId === itemGroupId);
    
    if (hasPromotions) {
      return res.status(400).json({ 
        error: 'Cannot delete item group. It has promotions attached. Please delete the promotions first.' 
      });
    }
    
    await storage.deleteItemGroup(itemGroupId);
    res.status(204).send();
  } catch (error) {
    console.log('Delete item group error:', error);
    res.status(500).json({ error: 'Failed to delete item group' });
  }
});

// Admin API - Item Group UPCs Management
app.get('/api/admin/item-groups/:id/upcs', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const upcs = await storage.getItemGroupUpcs(itemGroupId);
    res.json(upcs);
  } catch (error) {
    console.log('Get item group UPCs error:', error);
    res.status(500).json({ error: 'Failed to get item group UPCs' });
  }
});

app.post('/api/admin/item-groups/:id/upcs', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.id);
    const { upc } = req.body;

    if (!upc) {
      return res.status(400).json({ error: 'UPC is required' });
    }

    const newUpc = await storage.addUpcToItemGroup({
      itemGroupId,
      upc,
    });

    res.status(201).json(newUpc);
  } catch (error: any) {
    console.log('Add UPC to item group error:', error);
    if (error.message?.includes('already exists')) {
      return res.status(400).json({ error: 'This item is already in the group' });
    }
    res.status(500).json({ error: 'Failed to add UPC to item group' });
  }
});

app.delete('/api/admin/item-groups/:groupId/upcs/:upc', async (req, res) => {
  try {
    const itemGroupId = parseInt(req.params.groupId);
    const upc = req.params.upc;
    
    await storage.deleteItemGroupUpcByCode(itemGroupId, upc);
    res.status(204).send();
  } catch (error) {
    console.log('Delete item group UPC by code error:', error);
    res.status(500).json({ error: 'Failed to delete item from group' });
  }
});

app.delete('/api/admin/item-group-upcs/:id', async (req, res) => {
  try {
    const upcId = parseInt(req.params.id);
    await storage.deleteItemGroupUpc(upcId);
    res.status(204).send();
  } catch (error) {
    console.log('Delete item group UPC error:', error);
    res.status(500).json({ error: 'Failed to delete item group UPC' });
  }
});

// Admin API - Promotions Management
app.get('/api/admin/promotions', async (req, res) => {
  try {
    const promotions = await storage.getAllPromotions();
    const promotionsWithLocations = await Promise.all(
      promotions.map(async (promo) => {
        const locations = await storage.getPromotionLocations(promo.id);
        return {
          ...promo,
          locationIds: locations.map(loc => loc.locationId),
        };
      })
    );
    res.json(promotionsWithLocations);
  } catch (error) {
    console.log('Get all promotions error:', error);
    res.status(500).json({ error: 'Failed to get promotions' });
  }
});

app.get('/api/admin/promotions/:id', async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    const promotion = await storage.getPromotionById(promotionId);
    
    if (!promotion) {
      return res.status(404).json({ error: 'Promotion not found' });
    }

    const locations = await storage.getPromotionLocations(promotionId);
    res.json({ ...promotion, locations });
  } catch (error) {
    console.log('Get promotion error:', error);
    res.status(500).json({ error: 'Failed to get promotion' });
  }
});

app.post('/api/admin/promotions', async (req, res) => {
  try {
    const { itemGroupId, quantity, discountType, price, amountOff, requiresLoyaltyId, isActive, startDate, endDate, locationIds } = req.body;

    if (!itemGroupId || !quantity) {
      return res.status(400).json({ error: 'Item group and quantity are required' });
    }

    const type = discountType || 'multipack';
    
    if (type === 'multipack' && !price) {
      return res.status(400).json({ error: 'Price is required for multi-pack promotions' });
    }
    
    if (type === 'amountoff' && !amountOff) {
      return res.status(400).json({ error: 'Amount off is required for amount-off promotions' });
    }

    const promotion = await storage.createPromotion({
      itemGroupId,
      quantity,
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
    console.log('Create promotion error:', error);
    res.status(500).json({ error: 'Failed to create promotion' });
  }
});

app.put('/api/admin/promotions/:id', async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    const { itemGroupId, quantity, discountType, price, amountOff, requiresLoyaltyId, isActive, startDate, endDate, locationIds } = req.body;

    const updates: any = {};
    if (itemGroupId !== undefined) updates.itemGroupId = itemGroupId;
    if (quantity !== undefined) updates.quantity = quantity;
    if (discountType !== undefined) updates.discountType = discountType;
    if (price !== undefined) updates.price = price ? price.toString() : null;
    if (amountOff !== undefined) updates.amountOff = amountOff ? amountOff.toString() : null;
    if (requiresLoyaltyId !== undefined) updates.requiresLoyaltyId = requiresLoyaltyId;
    if (isActive !== undefined) updates.isActive = isActive;
    if (startDate !== undefined) updates.startDate = startDate ? new Date(startDate) : null;
    if (endDate !== undefined) updates.endDate = endDate ? new Date(endDate) : null;

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

    const updatedPromotion = await storage.updatePromotion(promotionId, updates);
    
    if (!updatedPromotion) {
      return res.status(404).json({ error: 'Promotion not found' });
    }

    res.json(updatedPromotion);
  } catch (error) {
    console.log('Update promotion error:', error);
    res.status(500).json({ error: 'Failed to update promotion' });
  }
});

app.delete('/api/admin/promotions/:id', async (req, res) => {
  try {
    const promotionId = parseInt(req.params.id);
    await storage.deletePromotion(promotionId);
    res.status(204).send();
  } catch (error) {
    console.log('Delete promotion error:', error);
    res.status(500).json({ error: 'Failed to delete promotion' });
  }
});

app.get('/api/admin/pricebook/search', async (req, res) => {
  try {
    const query = req.query.q as string;
    
    if (!query || query.length < 2) {
      return res.json([]);
    }

    const results = await storage.searchPricebook(query);
    res.json(results);
  } catch (error) {
    console.log('Search pricebook error:', error);
    res.status(500).json({ error: 'Failed to search pricebook' });
  }
});

app.post('/api/admin/pricebook', async (req, res) => {
  try {
    const { upc, description } = req.body;
    
    if (!upc || !description) {
      return res.status(400).json({ error: 'UPC and description are required' });
    }

    // Accept any UPC length - just validate it's not empty
    if (!upc.trim()) {
      return res.status(400).json({ error: 'UPC cannot be empty' });
    }

    const newItem = await storage.createPricebookItem({ upc: upc.trim(), description });
    res.status(201).json(newItem);
  } catch (error: any) {
    console.log('Create pricebook item error:', error);
    if (error.message?.includes('duplicate') || error.message?.includes('unique')) {
      return res.status(400).json({ error: 'UPC already exists' });
    }
    res.status(500).json({ error: 'Failed to create pricebook item' });
  }
});

// POS API - Heartbeat & Presence Tracking
app.post('/api/pos/heartbeat', async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] 💓 Heartbeat from Store ${req.body.pdiStoreNumber || 'Unknown'}`);
  
  try {
    const { pdiStoreNumber, posId, posType, posIpAddress, edgeIpAddress, edgeVersion } = req.body;

    if (!pdiStoreNumber || !posType) {
      return res.status(400).json({ error: 'PDI store number and POS type are required' });
    }

    await storage.upsertPosPresence({
      pdiStoreNumber,
      posId,
      posType,
      posIpAddress,
      edgeIpAddress,
      edgeVersion,
    });

    res.json({ success: true, message: 'Heartbeat received' });
  } catch (error) {
    console.log('POS heartbeat error:', error);
    res.status(500).json({ error: 'Failed to process heartbeat' });
  }
});

app.get('/api/pos/presence', async (req, res) => {
  try {
    const presenceRecords = await storage.getAllPosPresence();
    res.json(presenceRecords);
  } catch (error) {
    console.log('Get POS presence error:', error);
    res.status(500).json({ error: 'Failed to get POS presence' });
  }
});

// POS Loyalty Integration API
app.post('/api/pos/customer-lookup', async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`\n[${timestamp}] 📞 POS Customer Lookup Request:`);
  console.log('  Body:', JSON.stringify(req.body, null, 2));
  
  try {
    const { loyaltyId, phone } = req.body;

    if (!loyaltyId && !phone) {
      console.log(`  ❌ Missing both loyaltyId and phone`);
      return res.status(400).json({ error: 'Either loyaltyId or phone is required' });
    }

    let user;
    if (loyaltyId) {
      console.log(`  🔍 Looking up by loyalty ID: ${loyaltyId}`);
      user = await storage.getUserByLoyaltyId(loyaltyId);
    } else if (phone) {
      console.log(`  🔍 Looking up by phone: ${phone}`);
      user = await storage.getUserByPhone(phone);
    }

    if (!user) {
      console.log(`  ❌ Customer not found`);
      return res.status(404).json({ error: 'Customer not found' });
    }

    const rewards = await storage.getUserRewards(user.id);
    const response = {
      customerId: user.id,
      firstName: user.firstName,
      lastName: user.lastName,
      loyaltyId: user.loyaltyId,
      phone: user.phone,
      pointsBalance: rewards?.points || 0,
    };
    
    console.log(`  ✅ Customer found: ${user.firstName} ${user.lastName} (${rewards?.points || 0} pts)`);
    res.json(response);
  } catch (error) {
    console.log('  ❌ Customer lookup error:', error);
    res.status(500).json({ error: 'Failed to lookup customer' });
  }
});

app.post('/api/pos/evaluate-promotions', async (req, res) => {
  try {
    const { pdiStoreNumber, items } = req.body;

    if (!pdiStoreNumber || !items || !Array.isArray(items)) {
      return res.status(400).json({ error: 'pdiStoreNumber and items array are required' });
    }

    const location = await storage.getLocationByPdiStoreNumber(pdiStoreNumber);
    if (!location) {
      return res.status(400).json({ error: 'Location not found' });
    }

    const activePromotions = await storage.getActivePromotionsForLocation(location.id);
    const itemPromotions: any[] = [];

    for (const item of items) {
      const upc = item.upc;
      const qty = item.quantity || 1;
      const originalPrice = parseFloat(item.price) || 0;

      for (const promo of activePromotions) {
        const upcs = await storage.getItemGroupUpcs(promo.itemGroupId);
        const upcList = upcs.map(u => u.upc);

        if (upcList.includes(upc)) {
          const promoQty = promo.quantity;
          const bundleCount = Math.floor(qty / promoQty);
          const discountType = promo.discountType || 'multipack';

          if (bundleCount > 0) {
            let totalDiscount = 0;
            let totalPromoPrice = 0;
            let totalRegularPrice = 0;
            let description = '';

            if (discountType === 'amountoff') {
              // Amount Off: Split discount evenly across bundle
              const amountOff = parseFloat(promo.amountOff?.toString() || '0');
              totalDiscount = amountOff * bundleCount;
              const regularPricePerBundle = originalPrice * promoQty;
              totalRegularPrice = regularPricePerBundle * bundleCount;
              totalPromoPrice = totalRegularPrice - totalDiscount;
              description = `${bundleCount} x ($${amountOff.toFixed(2)} off ${promoQty})`;
            } else {
              // Multi-pack: Set new price for bundle
              const promoPrice = parseFloat(promo.price?.toString() || '0');
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
                itemGroupName: promo.itemGroupName,
                discountType,
                quantity: promoQty,
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
    console.log('Evaluate promotions error:', error);
    res.status(500).json({ error: 'Failed to evaluate promotions' });
  }
});

app.post('/api/pos/calculate-redemption', async (req, res) => {
  const timestamp = new Date().toISOString();
  console.log(`\n[${timestamp}] 💰 POS Calculate Redemption Request:`);
  console.log('  Body:', JSON.stringify(req.body, null, 2));
  
  try {
    const { customerId, eligibleSubtotal, lineItems } = req.body;

    if (!customerId || eligibleSubtotal === undefined) {
      console.log(`  ❌ Missing required fields`);
      return res.status(400).json({ error: 'customerId and eligibleSubtotal are required' });
    }

    // Log product line items
    if (lineItems && lineItems.length > 0) {
      console.log(`\n  🛒 TRANSACTION ITEMS (${lineItems.length} items):`);
      lineItems.forEach((item: any, idx: number) => {
        const amount = typeof item.amount === 'number' ? item.amount : parseFloat(item.amount) || 0;
        console.log(`     ${idx + 1}. UPC: ${item.upc || 'N/A'}`);
        console.log(`        Desc: ${item.description || 'N/A'}`);
        console.log(`        Qty: ${item.quantity || 1}, Amount: $${amount.toFixed(2)}`);
      });
      console.log('');
    }

    const rewards = await storage.getUserRewards(customerId);
    const pointsBalance = rewards?.points || 0;

    const subtotal = parseFloat(eligibleSubtotal.toString());
    
    // Redemption based ONLY on points balance (100 points = $1, max $10)
    const maxByPoints = Math.floor(pointsBalance / 100);
    const redeemDollars = Math.min(maxByPoints, 10);
    const pointsToUse = redeemDollars * 100;

    console.log(`  📊 Calculation: subtotal=$${subtotal}, points=${pointsBalance}, redemption=$${redeemDollars}`);

    res.json({
      pointsBalance,
      eligibleSubtotal: subtotal.toFixed(2),
      maxRedemptionByPoints: maxByPoints,
      recommendedRedemption: redeemDollars,
      pointsToRedeem: pointsToUse,
      newBalance: pointsBalance - pointsToUse,
    });
  } catch (error) {
    console.log('Calculate redemption error:', error);
    res.status(500).json({ error: 'Failed to calculate redemption' });
  }
});

app.post('/api/pos/finalize-transaction', async (req, res) => {
  try {
    const { customerId, eligibleSubtotal, pointsRedeemed, transactionId } = req.body;

    if (!customerId || eligibleSubtotal === undefined) {
      return res.status(400).json({ error: 'customerId and eligibleSubtotal are required' });
    }

    const subtotal = parseFloat(eligibleSubtotal.toString());
    const pointsEarned = Math.floor(subtotal * 5);
    const pointsUsed = parseInt(pointsRedeemed || '0');

    if (pointsUsed > 0) {
      await storage.addRewardPoints(
        customerId,
        -pointsUsed,
        `Points Redeemed - Transaction ${transactionId || 'N/A'}`
      );
    }

    if (pointsEarned > 0) {
      await storage.addRewardPoints(
        customerId,
        pointsEarned,
        `Purchase - Transaction ${transactionId || 'N/A'}`
      );
    }

    const rewards = await storage.getUserRewards(customerId);
    const newBalance = rewards?.points || 0;

    res.json({
      success: true,
      pointsEarned,
      pointsRedeemed: pointsUsed,
      newBalance,
      message: `Transaction complete. Earned ${pointsEarned} points, redeemed ${pointsUsed} points.`,
    });
  } catch (error) {
    console.log('Finalize transaction error:', error);
    res.status(500).json({ error: 'Failed to finalize transaction' });
  }
});

// Serve index.html for all other routes in production (SPA fallback)
if (isProduction) {
  app.use((req, res) => {
    res.sendFile(path.join(__dirname, '..', 'dist', 'index.html'));
  });
}

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Backend API server running on port ${PORT}`);
  console.log(`Environment: ${isProduction ? 'production' : 'development'}`);
});
