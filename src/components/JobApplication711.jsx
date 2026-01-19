import { useState } from 'react';

const STORE_ADDRESS = "3599 East-West Hwy, Hyattsville, MD 20782";
const STORE_OPENING_DATE = "February 10, 2026";

export default function JobApplication711() {
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    phone: '',
    email: '',
    dateOfBirth: '',
    isOver18: null,
    position: '',
    employmentType: '',
    availableShifts: [],
    startDate: '',
    previousExperience: '',
    retailExperience: null,
    authorizedToWork: null,
    canLiftAndStand: null,
    whyWorkHere: '',
    referralSource: ''
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const positions = [
    'Sales Associate / Cashier',
    'Food Service Team Member',
    'Stock Clerk',
    'Shift Lead',
    'Assistant Manager'
  ];

  const shifts = [
    'Morning (6am-2pm)',
    'Afternoon (2pm-10pm)',
    'Overnight (10pm-6am)',
    'Weekends'
  ];

  const referralSources = [
    'Walk-in / Saw Sign',
    'Online Job Board',
    'Friend or Family',
    'Social Media',
    'Other'
  ];

  const handleChange = (e) => {
    const { name, value, type } = e.target;
    if (type === 'checkbox') {
      const currentShifts = [...formData.availableShifts];
      if (e.target.checked) {
        currentShifts.push(value);
      } else {
        const idx = currentShifts.indexOf(value);
        if (idx > -1) currentShifts.splice(idx, 1);
      }
      setFormData({ ...formData, availableShifts: currentShifts });
    } else {
      setFormData({ ...formData, [name]: value });
    }
  };

  const handleRadio = (name, value) => {
    setFormData({ ...formData, [name]: value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!formData.firstName || !formData.lastName || !formData.phone || !formData.email) {
      setError('Please fill in all required fields.');
      return;
    }
    if (!formData.dateOfBirth) {
      setError('Please enter your date of birth.');
      return;
    }
    if (formData.isOver18 === null) {
      setError('Please confirm if you are 18 or older.');
      return;
    }
    if (!formData.position) {
      setError('Please select a position.');
      return;
    }
    if (!formData.employmentType) {
      setError('Please select employment type.');
      return;
    }
    if (formData.availableShifts.length === 0) {
      setError('Please select at least one available shift.');
      return;
    }
    if (!formData.startDate) {
      setError('Please enter when you can start.');
      return;
    }
    if (formData.authorizedToWork === null) {
      setError('Please confirm work authorization.');
      return;
    }
    if (formData.canLiftAndStand === null) {
      setError('Please confirm physical requirements.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch('/api/job-applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          availableShifts: formData.availableShifts.join(', '),
          storeLocation: STORE_ADDRESS + ' (Opening: ' + STORE_OPENING_DATE + ')'
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to submit application');
      }

      setSubmitted(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <img 
            src="https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/7-eleven_logo.svg/1200px-7-eleven_logo.svg.png"
            alt="7-Eleven Logo"
            style={styles.logo}
          />
          <div style={styles.successBox}>
            <div style={styles.checkmark}>✓</div>
            <h2 style={styles.successTitle}>Application Submitted!</h2>
            <p style={styles.successText}>
              Thank you for applying to join our team at 7-Eleven!
            </p>
            <p style={styles.successText}>
              We will review your application and contact you soon.
            </p>
            <p style={{ ...styles.successText, marginTop: '24px', fontSize: '14px', color: '#666' }}>
              Store Location: {STORE_ADDRESS}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <img 
          src="https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/7-eleven_logo.svg/1200px-7-eleven_logo.svg.png"
          alt="7-Eleven Logo"
          style={styles.logo}
        />
        
        <h1 style={styles.title}>Join Our Team!</h1>
        <p style={styles.subtitle}>Now Hiring at Our New Location</p>
        <p style={styles.address}>{STORE_ADDRESS}</p>
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <span style={styles.openingDate}>Store Opening: {STORE_OPENING_DATE}</span>
        </div>

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.section}>
            <h3 style={styles.sectionTitle}>Personal Information</h3>
            
            <div style={styles.row}>
              <div style={styles.field}>
                <label style={styles.label}>First Name *</label>
                <input
                  type="text"
                  name="firstName"
                  value={formData.firstName}
                  onChange={handleChange}
                  style={styles.input}
                  placeholder="First name"
                />
              </div>
              <div style={styles.field}>
                <label style={styles.label}>Last Name *</label>
                <input
                  type="text"
                  name="lastName"
                  value={formData.lastName}
                  onChange={handleChange}
                  style={styles.input}
                  placeholder="Last name"
                />
              </div>
            </div>

            <div style={styles.row}>
              <div style={styles.field}>
                <label style={styles.label}>Phone Number *</label>
                <input
                  type="tel"
                  name="phone"
                  value={formData.phone}
                  onChange={handleChange}
                  style={styles.input}
                  placeholder="(555) 555-5555"
                />
              </div>
              <div style={styles.field}>
                <label style={styles.label}>Email Address *</label>
                <input
                  type="email"
                  name="email"
                  value={formData.email}
                  onChange={handleChange}
                  style={styles.input}
                  placeholder="email@example.com"
                />
              </div>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Date of Birth *</label>
              <input
                type="date"
                name="dateOfBirth"
                value={formData.dateOfBirth}
                onChange={handleChange}
                style={styles.input}
              />
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Are you 18 years or older? *</label>
              <div style={styles.radioGroup}>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="isOver18"
                    checked={formData.isOver18 === true}
                    onChange={() => handleRadio('isOver18', true)}
                    style={styles.radio}
                  />
                  Yes
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="isOver18"
                    checked={formData.isOver18 === false}
                    onChange={() => handleRadio('isOver18', false)}
                    style={styles.radio}
                  />
                  No
                </label>
              </div>
            </div>
          </div>

          <div style={styles.section}>
            <h3 style={styles.sectionTitle}>Position & Availability</h3>
            
            <div style={styles.field}>
              <label style={styles.label}>Position Desired *</label>
              <select
                name="position"
                value={formData.position}
                onChange={handleChange}
                style={styles.select}
              >
                <option value="">Select a position...</option>
                {positions.map(pos => (
                  <option key={pos} value={pos}>{pos}</option>
                ))}
              </select>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Employment Type *</label>
              <div style={styles.radioGroup}>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="employmentType"
                    value="Full-time"
                    checked={formData.employmentType === 'Full-time'}
                    onChange={handleChange}
                    style={styles.radio}
                  />
                  Full-time
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="employmentType"
                    value="Part-time"
                    checked={formData.employmentType === 'Part-time'}
                    onChange={handleChange}
                    style={styles.radio}
                  />
                  Part-time
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="employmentType"
                    value="Either"
                    checked={formData.employmentType === 'Either'}
                    onChange={handleChange}
                    style={styles.radio}
                  />
                  Either
                </label>
              </div>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Available Shifts * (select all that apply)</label>
              <div style={styles.checkboxGroup}>
                {shifts.map(shift => (
                  <label key={shift} style={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      value={shift}
                      checked={formData.availableShifts.includes(shift)}
                      onChange={handleChange}
                      style={styles.checkbox}
                    />
                    {shift}
                  </label>
                ))}
              </div>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>When can you start? *</label>
              <input
                type="text"
                name="startDate"
                value={formData.startDate}
                onChange={handleChange}
                style={styles.input}
                placeholder="Immediately, 2 weeks, specific date..."
              />
            </div>
          </div>

          <div style={styles.section}>
            <h3 style={styles.sectionTitle}>Experience</h3>
            
            <div style={styles.field}>
              <label style={styles.label}>Have you worked in retail or convenience stores before?</label>
              <div style={styles.radioGroup}>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="retailExperience"
                    checked={formData.retailExperience === true}
                    onChange={() => handleRadio('retailExperience', true)}
                    style={styles.radio}
                  />
                  Yes
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="retailExperience"
                    checked={formData.retailExperience === false}
                    onChange={() => handleRadio('retailExperience', false)}
                    style={styles.radio}
                  />
                  No
                </label>
              </div>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Previous Work Experience (optional)</label>
              <textarea
                name="previousExperience"
                value={formData.previousExperience}
                onChange={handleChange}
                style={styles.textarea}
                placeholder="Brief description of your previous job(s)..."
                rows={3}
              />
            </div>
          </div>

          <div style={styles.section}>
            <h3 style={styles.sectionTitle}>Requirements</h3>
            
            <div style={styles.field}>
              <label style={styles.label}>Are you legally authorized to work in the United States? *</label>
              <div style={styles.radioGroup}>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="authorizedToWork"
                    checked={formData.authorizedToWork === true}
                    onChange={() => handleRadio('authorizedToWork', true)}
                    style={styles.radio}
                  />
                  Yes
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="authorizedToWork"
                    checked={formData.authorizedToWork === false}
                    onChange={() => handleRadio('authorizedToWork', false)}
                    style={styles.radio}
                  />
                  No
                </label>
              </div>
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Can you stand for extended periods and lift up to 30 lbs? *</label>
              <div style={styles.radioGroup}>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="canLiftAndStand"
                    checked={formData.canLiftAndStand === true}
                    onChange={() => handleRadio('canLiftAndStand', true)}
                    style={styles.radio}
                  />
                  Yes
                </label>
                <label style={styles.radioLabel}>
                  <input
                    type="radio"
                    name="canLiftAndStand"
                    checked={formData.canLiftAndStand === false}
                    onChange={() => handleRadio('canLiftAndStand', false)}
                    style={styles.radio}
                  />
                  No
                </label>
              </div>
            </div>
          </div>

          <div style={styles.section}>
            <h3 style={styles.sectionTitle}>Additional Information</h3>
            
            <div style={styles.field}>
              <label style={styles.label}>Why do you want to work at 7-Eleven? (optional)</label>
              <textarea
                name="whyWorkHere"
                value={formData.whyWorkHere}
                onChange={handleChange}
                style={styles.textarea}
                placeholder="Tell us a bit about yourself..."
                rows={3}
              />
            </div>

            <div style={styles.field}>
              <label style={styles.label}>How did you hear about this job?</label>
              <select
                name="referralSource"
                value={formData.referralSource}
                onChange={handleChange}
                style={styles.select}
              >
                <option value="">Select...</option>
                {referralSources.map(src => (
                  <option key={src} value={src}>{src}</option>
                ))}
              </select>
            </div>
          </div>

          {error && <div style={styles.error}>{error}</div>}

          <button 
            type="submit" 
            style={styles.submitBtn}
            disabled={submitting}
          >
            {submitting ? 'Submitting...' : 'Submit Application'}
          </button>
        </form>

        <p style={styles.footer}>
          7-Eleven is an Equal Opportunity Employer
        </p>
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #006241 0%, #00473a 100%)',
    padding: '20px',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'flex-start',
  },
  card: {
    background: '#ffffff',
    borderRadius: '16px',
    padding: '32px',
    maxWidth: '600px',
    width: '100%',
    boxShadow: '0 10px 40px rgba(0,0,0,0.3)',
  },
  logo: {
    display: 'block',
    margin: '0 auto 24px',
    height: '80px',
    objectFit: 'contain',
  },
  title: {
    textAlign: 'center',
    color: '#006241',
    fontSize: '28px',
    fontWeight: 'bold',
    margin: '0 0 8px 0',
  },
  subtitle: {
    textAlign: 'center',
    color: '#F7941D',
    fontSize: '18px',
    fontWeight: '600',
    margin: '0 0 8px 0',
  },
  address: {
    textAlign: 'center',
    color: '#666',
    fontSize: '14px',
    margin: '0 0 8px 0',
  },
  openingDate: {
    textAlign: 'center',
    color: '#006241',
    fontSize: '16px',
    fontWeight: '600',
    margin: '0 0 24px 0',
    padding: '8px 16px',
    background: '#e8f5e9',
    borderRadius: '20px',
    display: 'inline-block',
    width: 'fit-content',
    marginLeft: 'auto',
    marginRight: 'auto',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  section: {
    background: '#f8f9fa',
    borderRadius: '12px',
    padding: '20px',
    marginBottom: '16px',
  },
  sectionTitle: {
    color: '#006241',
    fontSize: '16px',
    fontWeight: '600',
    marginTop: 0,
    marginBottom: '16px',
    paddingBottom: '8px',
    borderBottom: '2px solid #F7941D',
  },
  row: {
    display: 'flex',
    gap: '16px',
    flexWrap: 'wrap',
  },
  field: {
    flex: '1 1 200px',
    marginBottom: '16px',
  },
  label: {
    display: 'block',
    marginBottom: '6px',
    color: '#333',
    fontSize: '14px',
    fontWeight: '500',
  },
  input: {
    width: '100%',
    padding: '12px',
    border: '2px solid #ddd',
    borderRadius: '8px',
    fontSize: '16px',
    boxSizing: 'border-box',
    transition: 'border-color 0.2s',
  },
  select: {
    width: '100%',
    padding: '12px',
    border: '2px solid #ddd',
    borderRadius: '8px',
    fontSize: '16px',
    boxSizing: 'border-box',
    background: 'white',
  },
  textarea: {
    width: '100%',
    padding: '12px',
    border: '2px solid #ddd',
    borderRadius: '8px',
    fontSize: '16px',
    boxSizing: 'border-box',
    resize: 'vertical',
    fontFamily: 'inherit',
  },
  radioGroup: {
    display: 'flex',
    gap: '20px',
    flexWrap: 'wrap',
  },
  radioLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  radio: {
    width: '18px',
    height: '18px',
    accentColor: '#006241',
  },
  checkboxGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  checkbox: {
    width: '18px',
    height: '18px',
    accentColor: '#006241',
  },
  error: {
    background: '#fee',
    color: '#c00',
    padding: '12px',
    borderRadius: '8px',
    marginBottom: '16px',
    fontSize: '14px',
  },
  submitBtn: {
    background: 'linear-gradient(135deg, #F7941D 0%, #E8820D 100%)',
    color: 'white',
    border: 'none',
    padding: '16px 32px',
    borderRadius: '8px',
    fontSize: '18px',
    fontWeight: 'bold',
    cursor: 'pointer',
    marginTop: '8px',
    boxShadow: '0 4px 12px rgba(247, 148, 29, 0.4)',
  },
  footer: {
    textAlign: 'center',
    color: '#999',
    fontSize: '12px',
    marginTop: '24px',
    marginBottom: 0,
  },
  successBox: {
    textAlign: 'center',
    padding: '40px 20px',
  },
  checkmark: {
    width: '80px',
    height: '80px',
    background: 'linear-gradient(135deg, #006241 0%, #00473a 100%)',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 24px',
    color: 'white',
    fontSize: '40px',
    fontWeight: 'bold',
  },
  successTitle: {
    color: '#006241',
    fontSize: '24px',
    marginBottom: '16px',
  },
  successText: {
    color: '#333',
    fontSize: '16px',
    margin: '8px 0',
  },
};
