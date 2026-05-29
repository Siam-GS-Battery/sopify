const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
require('dotenv').config();

const app = express();

// Middleware
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// In-memory database (แทน MongoDB)
let employees = [];
let idCounter = 1;

// Routes

// Get all employees
app.get('/api/employees', (req, res) => {
  try {
    // Sort by createdAt descending
    const sorted = [...employees].sort((a, b) => 
      new Date(b.createdAt) - new Date(a.createdAt)
    );
    res.json(sorted);
  } catch (error) {
    res.status(500).json({ message: 'Error fetching employees', error: error.message });
  }
});

// Get employee by ID
app.get('/api/employees/:id', (req, res) => {
  try {
    const employee = employees.find(emp => emp._id === req.params.id);
    if (!employee) {
      return res.status(404).json({ message: 'Employee not found' });
    }
    res.json(employee);
  } catch (error) {
    res.status(500).json({ message: 'Error fetching employee', error: error.message });
  }
});

// Create new employee
app.post('/api/employees', (req, res) => {
  try {
    // Check if email already exists
    const existingEmail = employees.find(emp => emp.email === req.body.email);
    if (existingEmail) {
      return res.status(400).json({ message: 'Email already exists' });
    }

    const newEmployee = {
      _id: String(idCounter++),
      ...req.body,
      status: 'pending',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };

    employees.push(newEmployee);
    res.status(201).json(newEmployee);
  } catch (error) {
    res.status(500).json({ message: 'Error creating employee', error: error.message });
  }
});

// Update employee status
app.patch('/api/employees/:id/status', (req, res) => {
  try {
    const { status } = req.body;
    
    if (!['pending', 'approved', 'rejected'].includes(status)) {
      return res.status(400).json({ message: 'Invalid status' });
    }

    const empIndex = employees.findIndex(emp => emp._id === req.params.id);
    
    if (empIndex === -1) {
      return res.status(404).json({ message: 'Employee not found' });
    }

    employees[empIndex] = {
      ...employees[empIndex],
      status,
      updatedAt: new Date().toISOString()
    };

    res.json(employees[empIndex]);
  } catch (error) {
    res.status(500).json({ message: 'Error updating employee status', error: error.message });
  }
});

// Update employee
app.put('/api/employees/:id', (req, res) => {
  try {
    const empIndex = employees.findIndex(emp => emp._id === req.params.id);
    
    if (empIndex === -1) {
      return res.status(404).json({ message: 'Employee not found' });
    }

    employees[empIndex] = {
      ...employees[empIndex],
      ...req.body,
      _id: employees[empIndex]._id, // Keep the same ID
      updatedAt: new Date().toISOString()
    };

    res.json(employees[empIndex]);
  } catch (error) {
    res.status(500).json({ message: 'Error updating employee', error: error.message });
  }
});

// Delete employee
app.delete('/api/employees/:id', (req, res) => {
  try {
    const empIndex = employees.findIndex(emp => emp._id === req.params.id);
    
    if (empIndex === -1) {
      return res.status(404).json({ message: 'Employee not found' });
    }

    employees.splice(empIndex, 1);
    res.json({ message: 'Employee deleted successfully' });
  } catch (error) {
    res.status(500).json({ message: 'Error deleting employee', error: error.message });
  }
});

// Get employees by status
app.get('/api/employees/status/:status', (req, res) => {
  try {
    const { status } = req.params;
    
    if (!['pending', 'approved', 'rejected'].includes(status)) {
      return res.status(400).json({ message: 'Invalid status' });
    }

    const filtered = employees
      .filter(emp => emp.status === status)
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    
    res.json(filtered);
  } catch (error) {
    res.status(500).json({ message: 'Error fetching employees', error: error.message });
  }
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'OK', 
    message: 'Server is running',
    timestamp: new Date().toISOString(),
    database: 'In-Memory',
    totalEmployees: employees.length
  });
});

// 5000 is taken by macOS ControlCenter (AirPlay Receiver) by default, so
// default to 5001. Override with PORT in server/.env if needed.
const PORT = process.env.PORT || 5001;

app.listen(PORT, () => {
  console.log(`🚀 Server is running on port ${PORT}`);
  console.log(`📊 Database: In-Memory (${employees.length} employees)`);
});
