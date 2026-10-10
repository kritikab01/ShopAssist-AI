-- 10 FAKE orders for testing. Names, phones and e-mails are invented.
-- Phone numbers use the +91 90000 0000x range, which is not assigned to real people here.
-- TIP: for the Twilio demo, change ONE order's phone to your own Twilio-verified number
--      (a Twilio trial account can only send SMS to verified numbers).

INSERT INTO orders (order_id, customer_name, phone, email, items, amount_inr, payment_method,
                    status, city, order_date, expected_delivery, courier, tracking_no) VALUES
('UT1001','Aarav Sharma',  '+919000000001','aarav@example.com',  '2 x Basics Cotton T-shirt (M)',            898.00,'UPI',       'delivered',       'Bengaluru','2026-09-20','2026-09-23','BlueDart','BD100200301'),
('UT1002','Priya Nair',    '+919000000002','priya@example.com',  '1 x Linen Kurta (S), 1 x Palazzo (S)',    2499.00,'Card',      'shipped',         'Kochi',    '2026-10-04','2026-10-11','Delhivery','DL55500112'),
('UT1003','Rohan Gupta',   '+919000000003','rohan@example.com',  '1 x Slim Fit Jeans (32)',                 1799.00,'COD',       'delayed',         'Lucknow',  '2026-10-01','2026-10-09','Ekart',   'EK77701234'),
('UT1004','Sneha Iyer',    '+919000000004','sneha@example.com',  '1 x Denim Jacket (M), 2 x Hoodie (M)',    7499.00,'Card',      'delivered',       'Chennai',  '2026-09-25','2026-09-28','BlueDart','BD100200355'),
('UT1005','Vikram Singh',  '+919000000005','vikram@example.com', '3 x Oxford Shirt (L)',                    4497.00,'NetBanking','out_for_delivery','Delhi',    '2026-10-07','2026-10-10','Delhivery','DL55500178'),
('UT1006','Ananya Das',    '+919000000006','ananya@example.com', '1 x Printed Kurta Set (L)',               1599.00,'COD',       'placed',          'Kolkata',  '2026-10-09','2026-10-14',NULL,      NULL),
('UT1007','Karan Mehta',   '+919000000007','karan@example.com',  '1 x Oversized Hoodie (XL)',               1299.00,'UPI',       'packed',          'Mumbai',   '2026-10-08','2026-10-11',NULL,      NULL),
('UT1008','Meera Reddy',   '+919000000008','meera@example.com',  '1 x Wool Blazer (M), 1 x Chinos (30)',    6299.00,'Card',      'returned',        'Hyderabad','2026-09-15','2026-09-18','BlueDart','BD100200399'),
('UT1009','Arjun Patel',   '+919000000009','arjun@example.com',  '1 x Graphic T-shirt (L)',                  599.00,'COD',       'cancelled',       'Ahmedabad','2026-10-02',NULL,        NULL,      NULL),
('UT1010','Fatima Khan',   '+919000000010','fatima@example.com', '2 x Relaxed Jeans (28), 1 x Crop Top (S)',3297.00,'UPI',       'shipped',         'Pune',     '2026-10-06','2026-10-10','Ekart',   'EK77701299')
ON CONFLICT (order_id) DO NOTHING;

-- 12 FAKE products (some deliberately low on stock so the Inventory Agent has work to do).
INSERT INTO products (sku, name, category, size, price_inr, stock, reorder_level, supplier, supplier_phone, unit_cost_inr) VALUES
('TSH-BAS-M', 'Basics Cotton T-shirt',   'T-shirts', 'M',  449.00, 42, 20, 'Tiruppur Knits',   '+919000000101', 180.00),
('TSH-BAS-L', 'Basics Cotton T-shirt',   'T-shirts', 'L',  449.00,  6, 20, 'Tiruppur Knits',   '+919000000101', 180.00),
('TSH-GRA-L', 'Graphic T-shirt',         'T-shirts', 'L',  599.00, 18, 10, 'Tiruppur Knits',   '+919000000101', 230.00),
('KUR-LIN-S', 'Linen Kurta',             'Kurtas',   'S', 1699.00,  3, 8,  'Jaipur Handloom',  '+919000000102', 720.00),
('KUR-LIN-M', 'Linen Kurta',             'Kurtas',   'M', 1699.00, 14, 8,  'Jaipur Handloom',  '+919000000102', 720.00),
('JNS-SLM-32','Slim Fit Jeans',          'Jeans',    '32',1799.00, 25, 12, 'Ahmedabad Denim',  '+919000000103', 760.00),
('JNS-RLX-28','Relaxed Jeans',           'Jeans',    '28',1499.00,  0, 10, 'Ahmedabad Denim',  '+919000000103', 640.00),
('HOD-OVR-XL','Oversized Hoodie',        'Hoodies',  'XL',1299.00,  9, 10, 'Ludhiana Woollens','+919000000104', 520.00),
('HOD-OVR-M', 'Oversized Hoodie',        'Hoodies',  'M', 1299.00, 30, 10, 'Ludhiana Woollens','+919000000104', 520.00),
('JKT-DEN-M', 'Denim Jacket',            'Jackets',  'M', 2999.00, 11, 5,  'Ahmedabad Denim',  '+919000000103', 1300.00),
('SHR-OXF-L', 'Oxford Shirt',            'Shirts',   'L', 1499.00, 22, 10, 'Bengaluru Shirts', '+919000000105', 610.00),
('PLZ-COT-S', 'Cotton Palazzo',          'Bottoms',  'S',  799.00,  4, 8,  'Jaipur Handloom',  '+919000000102', 300.00)
ON CONFLICT (sku) DO NOTHING;
