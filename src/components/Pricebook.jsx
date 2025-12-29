import { useState, useEffect } from 'react';

function Pricebook() {
  const [pricebookItems, setPricebookItems] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchTimeout, setSearchTimeout] = useState(null);

  useEffect(() => {
    loadPricebook();
  }, []);

  const loadPricebook = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/admin/pricebook');
      const data = await response.json();
      setPricebookItems(data.slice(0, 50)); // Show first 50 items by default
    } catch (error) {
      console.error('Error loading pricebook:', error);
    } finally {
      setLoading(false);
    }
  };

  const searchPricebook = async (query) => {
    if (!query || query.length < 2) {
      loadPricebook();
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`/api/admin/pricebook/search?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      setPricebookItems(data);
    } catch (error) {
      console.error('Error searching pricebook:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchChange = (value) => {
    setSearchQuery(value);
    
    if (searchTimeout) {
      clearTimeout(searchTimeout);
    }

    const timeout = setTimeout(() => searchPricebook(value), 300);
    setSearchTimeout(timeout);
  };

  return (
    <>
      <div className="section-header">
        <h2>Pricebook</h2>
      </div>
      <div className="search-container">
        <input
          type="text"
          className="search-input"
          placeholder="Search by UPC or description..."
          value={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>
      <div className="pricebook-grid">
        <div className="pricebook-item pricebook-header">
          <div>UPC</div>
          <div>Description</div>
        </div>
        {loading ? (
          <div className="pricebook-item">
            <div colSpan="2" style={{ textAlign: 'center', padding: '2rem' }}>Loading...</div>
          </div>
        ) : pricebookItems.length === 0 ? (
          <div className="pricebook-item">
            <div colSpan="2" style={{ textAlign: 'center', padding: '2rem' }}>No items found</div>
          </div>
        ) : (
          pricebookItems.map((item) => (
            <div key={item.upc} className="pricebook-item">
              <div>{item.upc}</div>
              <div>{item.description}</div>
            </div>
          ))
        )}
      </div>
    </>
  );
}

export default Pricebook;
