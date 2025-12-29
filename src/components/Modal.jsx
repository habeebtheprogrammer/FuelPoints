function Modal({ isOpen, onClose, title, children, onSubmit }) {
  if (!isOpen) return null;

  return (
    <div className="modal active" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <span className="close" onClick={onClose}>&times;</span>
        </div>
        <div className="modal-body">
          {children}
        </div>
        {onSubmit && (
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={onSubmit}>
              Save
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default Modal;
