import sqlite3
import math

def ozel_yuvarla(fiyat):
    # x4'e kadar aşağı, x5 ve üzerine (aslında kalan 0 olacağı için) bir sonraki 5'e
    # İstediğin kural: x0, x1, x2, x3, x4 -> x0 | x5, x6, x7, x8, x9 -> x5
    return math.floor(fiyat / 5) * 5

def veritabani_zam_uygula():
    try:
        # Veritabanı bağlantısı
        conn = sqlite3.connect('instance/cafe.db')
        cursor = conn.cursor()

        # 1. Mevcut verileri çek
        cursor.execute("SELECT id, name, price FROM product")
        products = cursor.fetchall()

        print(f"{'Ürün Adı':<20} | {'Eski':<8} | {'Zamlı':<8} | {'Yeni (5 Katı)':<8}")
        print("-" * 55)

        for row in products:
            p_id, p_name, old_price = row
            
            # %26 Zam Hesapla
            zamli_fiyat = old_price * 1.26
            
            # 5'in katına yuvarla
            new_price = ozel_yuvarla(zamli_fiyat)

            # 2. Veritabanını Güncelle
            cursor.execute("UPDATE product SET price = ? WHERE id = ?", (new_price, p_id))
            
            print(f"{p_name:<20} | {old_price:>8.2f} | {zamli_fiyat:>8.2f} | {new_price:>8.2f}")

        # 3. Değişiklikleri Kaydet
        conn.commit()
        print("\n[!] Tüm fiyatlar başarıyla güncellendi ve kaydedildi.")

    except sqlite3.Error as e:
        print(f"Hata oluştu: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    veritabani_zam_uygula()