import { useState, useEffect } from 'react';

function Signup() {
  useEffect(() => {
    document.body.style.overflow = 'auto';
    document.body.style.height = 'auto';
    return () => {
      document.body.style.overflow = '';
      document.body.style.height = '';
    };
  }, []);
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    phone: '',
    dateOfBirth: '',
    zipCode: '',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const formatPhone = (value) => {
    const digits = value.replace(/\D/g, '').slice(0, 10);
    if (digits.length >= 7) {
      return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
    } else if (digits.length >= 4) {
      return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
    } else if (digits.length > 0) {
      return `(${digits}`;
    }
    return '';
  };

  const handlePhoneChange = (e) => {
    const formatted = formatPhone(e.target.value);
    setFormData(prev => ({ ...prev, phone: formatted }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess(null);

    // Validate phone number (10 digits)
    const phoneDigits = formData.phone.replace(/\D/g, '');
    if (phoneDigits.length !== 10) {
      setError('Please enter a valid 10-digit phone number');
      setLoading(false);
      return;
    }

    // Validate password
    if (formData.password.length < 6) {
      setError('Password must be at least 6 characters');
      setLoading(false);
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      setLoading(false);
      return;
    }

    try {
      const response = await fetch('/api/public/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to create account');
      }

      setSuccess(data);
      setFormData({
        firstName: '',
        lastName: '',
        phone: '',
        dateOfBirth: '',
        zipCode: '',
        email: '',
        password: '',
        confirmPassword: '',
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="signup-page">
      <div className="signup-container">
        <div className="signup-header">
          <img src="/assets/birdies-logo.jpg" alt="Birdies Logo" className="signup-logo" />
          <h1>Join Birdies Rewards</h1>
          <p>Sign up for our loyalty program and start earning rewards today!</p>
        </div>

        {success ? (
          <div className="signup-success">
            <div className="success-icon">&#10003;</div>
            <h2>Welcome to Birdies!</h2>
            <p>Hi {success.customer.firstName}, you're all set!</p>
            <div className="loyalty-card">
              <div className="card-label">Your Loyalty ID</div>
              <div className="card-number">{success.customer.loyaltyId}</div>
              <div className="card-name">{success.customer.firstName} {success.customer.lastName}</div>
            </div>
            <p className="success-note">
              Show this number at checkout to earn points on every purchase!
              <br />5 points per dollar spent. 100 points = $1 off!
            </p>
            <button className="signup-btn" onClick={() => setSuccess(null)}>
              Sign Up Another Member
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="signup-form">
            {error && <div className="signup-error">{error}</div>}

            <div className="form-row">
              <div className="form-group">
                <label htmlFor="firstName">First Name *</label>
                <input
                  type="text"
                  id="firstName"
                  name="firstName"
                  value={formData.firstName}
                  onChange={handleChange}
                  required
                  placeholder="John"
                />
              </div>
              <div className="form-group">
                <label htmlFor="lastName">Last Name *</label>
                <input
                  type="text"
                  id="lastName"
                  name="lastName"
                  value={formData.lastName}
                  onChange={handleChange}
                  required
                  placeholder="Doe"
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="phone">Phone Number *</label>
              <input
                type="tel"
                id="phone"
                name="phone"
                value={formData.phone}
                onChange={handlePhoneChange}
                required
                placeholder="(555) 123-4567"
              />
            </div>

            <div className="form-group">
              <label htmlFor="dateOfBirth">Date of Birth *</label>
              <input
                type="date"
                id="dateOfBirth"
                name="dateOfBirth"
                value={formData.dateOfBirth}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="zipCode">Zip Code (Optional)</label>
              <input
                type="text"
                id="zipCode"
                name="zipCode"
                value={formData.zipCode}
                onChange={handleChange}
                placeholder="12345"
                maxLength={10}
              />
            </div>

            <div className="form-group">
              <label htmlFor="email">Email (Optional)</label>
              <input
                type="email"
                id="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="john@example.com"
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">Password *</label>
              <input
                type="password"
                id="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                required
                placeholder="At least 6 characters"
                minLength={6}
              />
            </div>

            <div className="form-group">
              <label htmlFor="confirmPassword">Confirm Password *</label>
              <input
                type="password"
                id="confirmPassword"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleChange}
                required
                placeholder="Confirm your password"
              />
            </div>

            <button type="submit" className="signup-btn" disabled={loading}>
              {loading ? 'Creating Account...' : 'Join Birdies Rewards'}
            </button>

            <p className="signup-terms">
              By signing up, you agree to receive promotional messages from Birdies.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

export default Signup;
