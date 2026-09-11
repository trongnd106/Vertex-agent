# Bộ Quy Tắc Ra Đề Toán Tính Nhẩm Cho Trẻ — Bsmart

> **Loại tài liệu:** Đặc tả chuẩn (canonical spec) mô tả bộ quy tắc dùng để **ra đề bài** tính nhẩm.
> **Đối tượng:** AI agent / hệ thống sinh đề; giáo viên; lập trình viên.
> **Phạm vi:** Phép **cộng** và phép **trừ** các số tự nhiên có 1–2 chữ số trở lên, phân loại cách giải theo 4 kỹ thuật bàn tính: *không công thức*, *anh bạn nhỏ*, *anh bạn lớn*, *mix*.

---

## 1. Mục đích

Tài liệu này định nghĩa:

1. **Các khái niệm** và ký hiệu dùng trong bộ quy tắc.
2. **4 kỹ thuật giải** và khi nào phải dùng kỹ thuật nào.
3. **Bảng quy tắc đầy đủ** cho phép cộng và phép trừ (theo chữ số tận cùng), kèm **số bài học**.
4. **Công thức tổng quát** để xác định kỹ thuật một cách lập trình hóa.
5. **Chương trình học (thứ tự 26 bài)** và quy tắc ra đề theo bài học.
6. **Quy trình ra đề** từng bước kèm ràng buộc.

---

## 2. Ký hiệu và phạm vi

Xét phép tính:

- **Cộng:** `A + B`
- **Trừ:** `A − B`

Trong đó:

| Ký hiệu | Ý nghĩa |
|---|---|
| `A` | Số thứ 1 (số bị cộng / số bị trừ). |
| `B` | Số thứ 2 (số cộng vào / số trừ đi). |
| `x` | Chữ số tận cùng của `A` (`x = A mod 10`). |
| `b` | Chữ số tận cùng của `B` (`b = B mod 10`). |

**Quy tắc cốt lõi:** *Mọi phép tính chỉ cần xét riêng cột hàng đơn vị.* Kỹ thuật được chọn hoàn toàn dựa trên cặp `(b, x)`. Các hàng chục trở lên xử lý như phép cộng/trừ thông thường (có nhớ / mượn 1).

Giới hạn chữ số của `A`, `B` do **cấp độ** quyết định (tài liệu không ấn định; mặc định gợi ý `1 ≤ A, B ≤ 99`).

---

## 3. Bốn kỹ thuật giải

| # | Kỹ thuật | Tên gọi | Bản chất | Khi nào xảy ra |
|---|---|---|---|---|
| 1 | **Không công thức** | tính trực tiếp | Thao tác hạt bàn tính trực tiếp, không cần mẹo "mượn – thêm". | Không vượt ngưỡng 5, không vượt ngưỡng 10 (hoặc đã có sẵn hạt 5 để dùng). |
| 2 | **Anh bạn nhỏ** | bạn nhỏ (bổ túc 5) | Dùng cặp số có tổng bằng **5**: `(1,4)`, `(2,3)`. Bạn nhỏ của `n` là `5 − n`. | Phép tính **vượt ngưỡng 5** trong phạm vi một cột. |
| 3 | **Anh bạn lớn** | bạn lớn (bổ túc 10) | Dùng cặp số có tổng bằng **10**: `(1,9),(2,8),(3,7),(4,6),(5,5)`. Bạn lớn của `n` là `10 − n`. | Phép tính **vượt ngưỡng 10** (có nhớ / mượn hàng chục). |
| 4 | **Mix** | kết hợp | Vừa phải mượn/thêm "bạn lớn" vừa phải mượn/thêm "bạn nhỏ" trong cùng một bước. | Vượt ngưỡng 10 **và** thao tác trung gian cũng vượt ngưỡng 5. |

### 3.1. Thao tác bàn tính tương ứng

Bàn tính mỗi cột có **1 hạt trên (giá trị 5)** và **4 hạt dưới (mỗi hạt giá trị 1)**. Một chữ số `x` được biểu diễn: hạt 5 (nếu `x ≥ 5`) + `(x mod 5)` hạt dưới.

| Tình huống | Thao tác | Ví dụ |
|---|---|---|
| Cộng qua 5 | Thêm hạt 5, **bớt bạn nhỏ** | `4 + 1`: thêm 5, bớt 4 → `5` |
| Trừ qua 5 (hạ xuống) | Bớt hạt 5, **thêm bạn nhỏ** | `5 − 1`: bớt 5, thêm 4 → `4` |
| Cộng qua 10 | **Bớt bạn lớn**, thêm 1 chục | `8 + 3`: bớt 7, thêm 1 chục → `11` |
| Trừ qua 10 (mượn chục) | **Thêm bạn lớn**, bớt 1 chục | `11 − 3`: bớt 1 chục, thêm 7 → `8` |
| Mix | Kết hợp bạn lớn + bạn nhỏ | `5 + 6`: bớt bạn lớn 4, nhưng `5 − 4` thiếu hạt → mượn bạn nhỏ → `11` |

---

## 4. Quy tắc phép cộng

**Phát biểu:** Cho phép cộng `A + B`. Gọi `x` là chữ số tận cùng của `A`, `b` là chữ số tận cùng của `B`. Kỹ thuật được chọn theo bảng dưới.

### 4.1. Bảng quy tắc chính thức (theo chữ số tận cùng `x`)

| `b` | Không công thức | Anh bạn nhỏ | Anh bạn lớn | Mix | Bài học |
|---|---|---|---|---|---|
| 1 | 0, 1, 2, 3, 5, 6, 7, 8 | 4 | 9 | — | 1 |
| 2 | 0, 1, 2, 5, 6, 7 | 3, 4 | 8, 9 | — | 2 |
| 3 | 0, 1, 5, 6 | 2, 3, 4 | 7, 8, 9 | — | 3 |
| 4 | 0, 5 | 1, 2, 3, 4 | 6, 7, 8, 9 | — | 4 |
| 5 | 0, 1, 2, 3, 4 | — | 5, 6, 7, 8, 9 | — | 5 |
| 6 | 0, 1, 2, 3 | — | 4, 9 | 5, 6, 7, 8 | 6; **mix: 19** |
| 7 | 0, 1, 2 | — | 3, 4, 8, 9 | 5, 6, 7 | 7; **mix: 20** |
| 8 | 0, 1 | — | 2, 3, 4, 7, 8, 9 | 5, 6 | 8; **mix: 21** |
| 9 | 0 | — | 1, 2, 3, 4, 6, 7, 8, 9 | 5 | 9; **mix: 22** |

*Dấu `—` nghĩa là không có giá trị `x` nào thuộc kỹ thuật đó với `b` tương ứng.*

*Cột "Bài học":* số bài học dạy quy tắc tương ứng. Với các dòng có **Mix**, phần cơ bản (Không công thức / Bạn lớn) học ở bài đầu, riêng kỹ thuật **Mix** chỉ dạy ở bài sau (19–22). Chi tiết xem mục 6.

### 4.2. Công thức tổng quát (để lập trình)

| Kỹ thuật | Điều kiện |
|---|---|
| Không công thức | `(x < 5` và `x + b < 5)` **hoặc** `(x ≥ 5` và `x + b < 10)` |
| Anh bạn nhỏ | `b ≤ 4` và `5 ≤ x + b < 10` |
| Anh bạn lớn | `x + b ≥ 10` và (`x < 5` **hoặc** `x ≥ 15 − b`) |
| Mix | `x + b ≥ 10` và `x ≥ 5` và `x < 15 − b` |

**Giải thích ngắn:**

- **Không công thức:** cộng hạt trực tiếp được vì không vượt ngưỡng 5 (khi `x < 5`) hoặc đã có hạt 5 và không vượt ngưỡng 10 (khi `x ≥ 5`).
- **Anh bạn nhỏ:** chỉ xảy ra khi cộng một số **nhỏ (b ≤ 4)** làm `x` vượt qua ngưỡng 5 nhưng chưa tới 10.
- **Anh bạn lớn:** vượt ngưỡng 10; việc "bớt bạn lớn `10 − b`" không buộc phải qua ngưỡng 5 (khi `x < 5`, hoặc `x` đủ lớn để bớt trực tiếp).
- **Mix:** vượt ngưỡng 10 nhưng `x` nằm vùng `[5, 9]` thấp → khi "bớt bạn lớn" cũng phải mượn bạn nhỏ.

### 4.3. Ví dụ phép cộng

| Phép tính | `(b, x)` | Kỹ thuật | Lời giải |
|---|---|---|---|
| `14 + 1` | `(1, 4)` | Bạn nhỏ | Thêm 5, bớt 4 → `15` |
| `29 + 1` | `(1, 9)` | Bạn lớn | Bớt 9, thêm 1 chục → `30` |
| `27 + 6` | `(6, 7)` | Mix | `7 + 6 = 13` → `33` |
| `34 + 7` | `(7, 4)` | Bạn lớn | `4 + 7`: bớt 3, thêm 1 chục → `41` |
| `35 + 6` | `(6, 5)` | Mix | `5 + 6`: bớt bạn lớn 4, mượn bạn nhỏ → `41` |

---

## 5. Quy tắc phép trừ

**Phát biểu:** Cho phép trừ `A − B`. Gọi `x` là chữ số tận cùng của `A`, `b` là chữ số tận cùng của `B`. Kỹ thuật được chọn theo bảng dưới.

**Điều kiện hợp lệ tổng quát:** kết quả không âm (`A ≥ B`). Các trường hợp **Bạn lớn / Mix** phải **mượn 1 chục**, nên bắt buộc `A ≥ 10` và `x < b`. Các trường hợp **Không công thức / Bạn nhỏ** không mượn chục (`x ≥ b`).

### 5.1. Bảng quy tắc chính thức (theo chữ số tận cùng `x`)

| `b` | Không công thức | Anh bạn nhỏ | Anh bạn lớn (mượn chục) | Mix | Bài học |
|---|---|---|---|---|---|
| 1 | 1, 2, 3, 4, 6, 7, 8, 9 | 5 | `x = 0`, `A` tròn chục (`A ≥ 10`) | — | 10 |
| 2 | 2, 3, 4, 7, 8, 9 | 5, 6 | `x = 1`, `A > 10` | — | 11 |
| 3 | 3, 4, 8, 9 | 5, 6, 7 | `x ∈ {0,1,2}`, `A > 10` | — | 12 |
| 4 | 4, 9 | 5, 6, 7, 8 | `x ∈ {0,1,2,3}`, `A > 10` | — | 13 |
| 5 | 5, 6, 7, 8, 9 | — | `x ∈ {0,1,2,3,4}`, `A > 10` | — | 14 |
| 6 | 6, 7, 8, 9 | — | `x ∈ {0,5}`, `A ≥ 10` | 1, 2, 3, 4 | 15; **mix: 23** |
| 7 | 7, 8, 9 | — | `x ∈ {0,1,5,6}`, `A ≥ 10` | 2, 3, 4 | 16; **mix: 24** |
| 8 | 8, 9 | — | `x ∈ {0,1,2,5,6,7}`, `A ≥ 10` | 3, 4 | 17; **mix: 25** |
| 9 | 9 | — | `x ∈ {0,1,2,3,5,6,7,8}`, `A ≥ 10` | 4 | 18; **mix: 26** |

*Cột "Bài học":* số bài học dạy quy tắc tương ứng. Với các dòng có **Mix**, phần cơ bản (Không công thức / Bạn lớn) học ở bài đầu, riêng kỹ thuật **Mix** chỉ dạy ở bài sau (23–26). Chi tiết xem mục 6.

**Chú thích cột "Anh bạn lớn":** ô này mô tả chữ số tận cùng `x` của `A` khi phép trừ **mượn 1 chục**, kèm điều kiện về giá trị của `A`. Ví dụ:
- Trừ 1, bạn lớn: `x = 0` và `A` tròn chục → `10 − 1 = 9`, `20 − 1 = 19`, …
- Trừ 2, bạn lớn: `x = 1` và `A > 10` → `11 − 2 = 9`, `21 − 2 = 19`, …

### 5.2. Công thức tổng quát (để lập trình)

**Nhánh 1 — không mượn chục (`x ≥ b`, kết quả đơn vị không âm):**

| Kỹ thuật | Điều kiện |
|---|---|
| Anh bạn nhỏ | `b ≤ 4` và `x ≥ 5` và `x < b + 5` |
| Không công thức | mọi trường hợp còn lại của nhánh này |

*Giải thích:* "Bạn nhỏ" dùng khi trừ một số **nhỏ (b ≤ 4)** mà `x` có hạt 5 nhưng không đủ hạt dưới để bớt trực tiếp → phải bớt hạt 5 rồi thêm bạn nhỏ `5 − b`. Ngoài ra thì trừ trực tiếp.

**Nhánh 2 — mượn chục (`x < b`, bắt buộc `A ≥ 10`):**
Hàng đơn vị mới = `x + 10 − b`.

| Kỹ thuật | Điều kiện |
|---|---|
| Anh bạn lớn | `x ≥ 5` **hoặc** `x + (10 − b) < 5` |
| Mix | `x < 5` và `x + (10 − b) ≥ 5` |

*Giải thích:* sau khi mượn chục, ta **thêm bạn lớn `10 − b`** vào hàng đơn vị. Nếu việc thêm này không vượt ngưỡng 5 (khi `x ≥ 5`, hoặc `x + 10 − b < 5`) → Bạn lớn thuần. Nếu `x` nhỏ và kết quả thêm vượt ngưỡng 5 → phải mượn thêm bạn nhỏ → **Mix**.

### 5.3. Ví dụ phép trừ

| Phép tính | `(b, x)` | Kỹ thuật | Lời giải |
|---|---|---|---|
| `15 − 1` | `(1, 5)` | Bạn nhỏ | Bớt hạt 5, thêm 4 → `14` |
| `10 − 1` | `(1, 0)` | Bạn lớn | Mượn chục, thêm bạn lớn 9 → `9` |
| `11 − 2` | `(2, 1)` | Bạn lớn | Mượn chục, thêm bạn lớn 8 → `9` |
| `13 − 7` | `(7, 3)` | Mix | Mượn chục, thêm bạn lớn 3 → `3 + 3 = 6` vượt 5 → bạn nhỏ → `6` |
| `15 − 6` | `(6, 5)` | Bạn lớn | Mượn chục, thêm bạn lớn 4 vào 5 → `9` |
| `24 − 8` | `(8, 4)` | Mix | Mượn chục, thêm bạn lớn 2 → `4 + 2 = 6` vượt 5 → bạn nhỏ → `16` |

---

## 6. Chương trình học (thứ tự bài học)

Bộ chương trình gồm **26 bài học** theo thứ tự tuyến tính. Mỗi dòng quy tắc được gán một **số bài học** (cột "Bài học" ở mục 4.1 / 5.1). Thứ tự như sau:

| Bài học | Nội dung |
|---|---|
| 1–5 | Cộng 1 → Cộng 5 (Không công thức, Bạn nhỏ, Bạn lớn) |
| 6–9 | Cộng 6 → Cộng 9 (Không công thức, Bạn lớn) |
| 10–14 | Trừ 1 → Trừ 5 (Không công thức, Bạn nhỏ, Bạn lớn) |
| 15–18 | Trừ 6 → Trừ 9 (Không công thức, Bạn lớn) |
| 19–22 | **Mix** của Cộng 6 → Cộng 9 |
| 23–26 | **Mix** của Trừ 6 → Trừ 9 |

### 6.1. Quy tắc ra đề theo bài học

> **Nguyên tắc:** hệ thống chỉ được ra đề các dạng **đã học tới bài hiện tại**. Học tới bài `N` thì chỉ ra đề các quy tắc có số bài học `≤ N`.

Áp dụng cụ thể:

- Học tới bài **12** (Trừ 3) → chỉ ra đề Cộng 1–9 và Trừ 1, 2, 3; **chưa** được ra Trừ 4 trở đi.
- Học tới bài **18** → được ra toàn bộ phần cơ bản (Cộng 1–9, Trừ 1–9) nhưng **chưa** được ra dạng **Mix** nào.
- Học tới bài **19–22** → mới được phép ra đề **Mix của phép cộng** (Cộng 6 → Cộng 9).
- Học tới bài **23–26** → mới được phép ra đề **Mix của phép trừ** (Trừ 6 → Trừ 9).

**Lưu ý khi ra đề dạng có cả cơ bản lẫn mix (vd Cộng 6):**
- Từ bài 6 đến bài 18: chỉ ra các trường hợp **Không công thức / Bạn lớn** của dòng đó, **không** được ra `x ∈ {5,6,7,8}` (mix).
- Từ bài 19 trở đi: được phép ra cả trường hợp **Mix** (`x ∈ {5,6,7,8}`).

### 6.2. Ví dụ chọn đề theo bài học

| Bài học hiện tại | Được phép ra đề |
|---|---|
| 1 | Cộng 1 (Không công thức, Bạn nhỏ, Bạn lớn) |
| 5 | Cộng 1 → Cộng 5 |
| 12 | Cộng 1–9, Trừ 1 → Trừ 3 |
| 18 | Cộng 1–9, Trừ 1 → Trừ 9 (chưa có Mix) |
| 19 | như bài 18 **+** Mix của Cộng 6 |
| 22 | như bài 19 **+** Mix của Cộng 7, 8, 9 |
| 26 | toàn bộ (gồm cả Mix của Trừ 6 → Trừ 9) |

---

## 7. Quy trình ra đề (dành cho hệ thống sinh đề)

Quy trình chuẩn để sinh một đề bài:

1. **Chọn phép tính:** cộng hoặc trừ.
2. **Xác định bài học hiện tại `N`:** lấy từ tiến độ chương trình (mục 6).
3. **Chọn kỹ thuật mục tiêu:** một trong 4 kỹ thuật ở mục 3 (hoặc chọn ngẫu nhiên có trọng số), **chỉ chọn kỹ thuật đã học tới bài `N`** (xem quy tắc mục 6.1).
4. **Chọn `b`:** chữ số tận cùng của `B` (`1..9`) — dòng tương ứng phải đã mở (số bài học `≤ N`).
5. **Chọn `x`:** chữ số tận cùng của `A`, lấy từ bảng quy tắc của phép tính (mục 4.1 / 5.1) ứng với dòng `b` và cột kỹ thuật đã chọn. Nếu cột đó là `—`, đổi `b` hoặc bỏ qua tổ hợp.
6. **Sinh `A`:** chọn giá trị có tận cùng `x`, trong phạm vi cấp độ, thỏa các ràng buộc riêng của phép trừ (xem mục 8).
7. **Sinh `B`:** chọn giá trị có tận cùng `b` (thường `1..9` hoặc `10..99`), thỏa `A ≥ B` (với phép trừ).
8. **Kiểm chứng:** tính lại bằng công thức tổng quát (mục 4.2 / 5.2) và xác nhận kỹ thuật thu được đúng như mục tiêu, đồng thời số bài học của dạng đó `≤ N`.

---

## 8. Ràng buộc và lưu ý khi sinh đề

| # | Ràng buộc | Áp dụng cho |
|---|---|---|
| 1 | Kết quả không âm: `A ≥ B` | Phép trừ (toàn bộ) |
| 2 | Phải có hàng chục để mượn: `A ≥ 10` | Phép trừ, kỹ thuật Bạn lớn và Mix |
| 3 | Điều kiện thêm của bảng 5.1 (vd `A > 10`, `A` tròn chục…) | Phép trừ, cột Bạn lớn |
| 4 | Nếu muốn giữ tổng không vượt quá mốc nhất định (vd `≤ 99`), phải kiểm tra cả hàng chục | Phép cộng, kỹ thuật Bạn lớn và Mix |
| 5 | Khi dạy trẻ mới bắt đầu, nên giới hạn phạm vi `A, B ≤ 20` | Mọi phép tính (gợi ý, không bắt buộc) |
| 6 | Chỉ ra đề các dạng có **số bài học ≤ bài hiện tại `N`**; không ra **Mix** trước bài 19 | Mọi phép tính (xem mục 6) |

---

## 9. Tham chiếu nhanh (bảng bổ túc)

| Loại bạn | Cặp số | Ý nghĩa |
|---|---|---|
| **Bạn nhỏ** (bổ túc 5) | `(1,4)`, `(2,3)` | Hai số cộng lại bằng 5 |
| **Bạn lớn** (bổ túc 10) | `(1,9)`, `(2,8)`, `(3,7)`, `(4,6)`, `(5,5)` | Hai số cộng lại bằng 10 |

- Cộng qua 5: **thêm 5, bớt bạn nhỏ** — ví dụ `4 + 1`.
- Trừ qua 5: **bớt 5, thêm bạn nhỏ** — ví dụ `5 − 1`.
- Cộng qua 10: **bớt bạn lớn, thêm 1 chục** — ví dụ `8 + 3`.
- Trừ qua 10: **thêm bạn lớn, bớt 1 chục** — ví dụ `11 − 3`.
- **Mix** = phối hợp hai loại trong một bước — ví dụ `5 + 6`, `13 − 7`.
