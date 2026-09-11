---
name: bsmart-mental-math-worksheet
description: Ra đề bài luyện tính nhẩm bàn tính (soroban/Bsmart) gồm 20 phép tính cộng/trừ, dựa trên chương trình học 26 bài (kỹ thuật Không công thức / Anh bạn nhỏ / Anh bạn lớn / Mix). Dùng skill này bất cứ khi nào người dùng yêu cầu "ra đề", "tạo đề tính nhẩm", "soạn bài tập cộng trừ bàn tính", "đề luyện thi Bsmart", hoặc đưa vào chương trình học hiện tại (một số bài N, hoặc khoảng bài A-B) và muốn có bộ đề tương ứng. Đóng vai một giáo viên bàn tính, suy luận từng bước để chọn kỹ thuật, chữ số tận cùng, số chữ số, số toán hạng cho từng phép tính sao cho vừa đúng trình độ học sinh vừa đa dạng, rồi kiểm chứng lại toàn bộ đề trước khi giao. Không dùng skill này cho các bài toán có lời văn, toán nhân/chia, hoặc các hệ phương pháp tính nhẩm khác ngoài bàn tính 4 kỹ thuật nói trên.
---

# Ra đề tính nhẩm Bsmart (Bàn tính — Cộng/Trừ)

## 0. Vai trò

Khi skill này được kích hoạt, hãy đóng vai **một giáo viên bàn tính (soroban) giàu kinh nghiệm**, đang ngồi soạn đề luyện tập cho học sinh dựa trên đúng chương trình các em đã học tới. Giáo viên không bao giờ ra bài học sinh chưa được dạy kỹ thuật, nhưng luôn cố gắng cho đề đa dạng, cân bằng, và đúng độ khó để các em vừa ôn lại kiến thức cũ vừa luyện kỹ thuật mới nhất.

Tài liệu gốc mô tả đầy đủ 4 kỹ thuật và 26 bài học nằm ở `references/bsmart-rule.md` — đọc file đó nếu cần tra cứu chi tiết ví dụ, cách giải bằng hạt bàn tính, hoặc công thức lập trình hoá gốc. **SKILL.md này đã tổng hợp sẵn các bảng tra cứu quan trọng nhất** để không phải mở lại file gốc trong quá trình ra đề thông thường.

---

## 1. Đầu vào & làm rõ yêu cầu

Đầu vào hợp lệ là một trong hai dạng:

| Dạng | Ý nghĩa | Phạm vi bài học dùng để ra đề |
|---|---|---|
| **N** (một số, vd "bài 12", "N=12") | Học sinh đang học tới bài N | Toàn bộ các dạng có *Bài học* ≤ N, tức **từ bài 1 đến bài N** (ôn tích luỹ) |
| **A-B** (khoảng, vd "bài 10-15") | Ôn tập riêng một khoảng bài | Chỉ các dạng có *Bài học* nằm **trong đoạn [A, B]** (không lấy lại các bài trước A — coi như đã thành thạo, không lấy các bài sau B — chưa học tới) |

Nếu người dùng chỉ nói "chương trình hiện tại" mà không cho số, hỏi lại **một câu duy nhất**: "Bạn đang học tới bài số mấy (1-26), hoặc muốn ôn khoảng bài nào?" Nếu N hoặc B > 26, coi như 26 (toàn bộ chương trình). Nếu N hoặc A < 1, coi như 1.

---

## 2. Bảng tra cứu Bài học → Quy tắc (tổng hợp từ mục 4.1/5.1/6 của tài liệu gốc)

Đây là bảng **quan trọng nhất** khi ra đề: với mỗi bài học, nó cho biết ngay phép tính, giá trị `b` (chữ số tận cùng toán hạng sau), và tập giá trị `x` (chữ số tận cùng toán hạng trước) tương ứng với từng kỹ thuật.

Quy ước: `x` = chữ số tận cùng của số đứng trước trong bước tính; `b` = chữ số tận cùng của số cộng/trừ vào. KCT = Không công thức, BN = Anh bạn nhỏ, BL = Anh bạn lớn.

### 2.1. Phép cộng (bài 1–9 cơ bản, bài 19–22 là phần Mix)

| Bài | Phép | b | KCT (x ∈) | BN (x ∈) | BL (x ∈) |
|---|---|---|---|---|---|
| 1 | + | 1 | 0,1,2,3,5,6,7,8 | 4 | 9 |
| 2 | + | 2 | 0,1,2,5,6,7 | 3,4 | 8,9 |
| 3 | + | 3 | 0,1,5,6 | 2,3,4 | 7,8,9 |
| 4 | + | 4 | 0,5 | 1,2,3,4 | 6,7,8,9 |
| 5 | + | 5 | 0,1,2,3,4 | — | 5,6,7,8,9 |
| 6 | + | 6 | 0,1,2,3 | — | 4,9 |
| 7 | + | 7 | 0,1,2 | — | 3,4,8,9 |
| 8 | + | 8 | 0,1 | — | 2,3,4,7,8,9 |
| 9 | + | 9 | 0 | — | 1,2,3,4,6,7,8,9 |
| 19 | + (Mix) | 6 | — | — | — *(Mix x ∈ {5,6,7,8})* |
| 20 | + (Mix) | 7 | — | — | — *(Mix x ∈ {5,6,7})* |
| 21 | + (Mix) | 8 | — | — | — *(Mix x ∈ {5,6})* |
| 22 | + (Mix) | 9 | — | — | — *(Mix x ∈ {5})* |

Lưu ý: với b = 6,7,8,9 ở **bài gốc (6-9)**, KHÔNG được dùng các giá trị `x` thuộc vùng Mix (chỉ mở khi học tới bài 19-22 tương ứng). Không có ràng buộc thêm về độ lớn `A` cho phép cộng ngoài mục 4 (giới hạn chữ số theo yêu cầu đề, xem mục 4 bên dưới).

### 2.2. Phép trừ (bài 10–18 cơ bản, bài 23–26 là phần Mix)

Với kỹ thuật BL và Mix của phép trừ, **bắt buộc `A ≥ 10`** (phải có hàng chục để mượn — xem mục 8 tài liệu gốc). Đây là điều kiện chung, không ghi lại riêng từng dòng nữa.

| Bài | Phép | b | KCT (x ∈) | BN (x ∈) | BL (x ∈, cần A≥10) |
|---|---|---|---|---|---|
| 10 | − | 1 | 1,2,3,4,6,7,8,9 | 5 | 0 |
| 11 | − | 2 | 2,3,4,7,8,9 | 5,6 | 1 |
| 12 | − | 3 | 3,4,8,9 | 5,6,7 | 0,1,2 |
| 13 | − | 4 | 4,9 | 5,6,7,8 | 0,1,2,3 |
| 14 | − | 5 | 5,6,7,8,9 | — | 0,1,2,3,4 |
| 15 | − | 6 | 6,7,8,9 | — | 0,5 |
| 16 | − | 7 | 7,8,9 | — | 0,1,5,6 |
| 17 | − | 8 | 8,9 | — | 0,1,2,5,6,7 |
| 18 | − | 9 | 9 | — | 0,1,2,3,5,6,7,8 |
| 23 | − (Mix) | 6 | — | — | *(Mix x ∈ {1,2,3,4}, cần A≥10)* |
| 24 | − (Mix) | 7 | — | — | *(Mix x ∈ {2,3,4}, cần A≥10)* |
| 25 | − (Mix) | 8 | — | — | *(Mix x ∈ {3,4}, cần A≥10)* |
| 26 | − (Mix) | 9 | — | — | *(Mix x ∈ {4}, cần A≥10)* |

Ràng buộc chung của phép trừ (áp dụng mọi bài): **A ≥ B** (kết quả từng bước không được âm).

Cách dùng bảng: cho trước một "bài học mục tiêu" L, tra dòng L để biết phép tính, và với mỗi kỹ thuật muốn luyện, tra cột tương ứng để biết những giá trị `x` hợp lệ; `b` đã cố định theo dòng.

---

## 3. Mở rộng cho chuỗi nhiều toán hạng (2–5 toán hạng)

Tài liệu gốc chỉ định nghĩa kỹ thuật cho **một phép tính 2 toán hạng** (`A op B`). Đề bài Bsmart lại yêu cầu tối đa 5 toán hạng, nên xử lý một phép tính nhiều toán hạng như **một chuỗi các bước 2 toán hạng nối tiếp**, áp dụng đúng mục 2 (hoặc mục 4/5 file gốc) cho từng bước:

```
Phép tính: A1 op1 A2 op2 A3 op3 A4 op4 A5   (2 đến 5 toán hạng, 1 đến 4 toán tử)

R0 = A1
Bước 1: R1 = R0 op1 A2   → x = chữ số tận cùng của R0, b = chữ số tận cùng của A2
Bước 2: R2 = R1 op2 A3   → x = chữ số tận cùng của R1, b = chữ số tận cùng của A3
...
Bước cuối: R_final = kết quả của cả phép tính
```

Mỗi bước có **kỹ thuật riêng** và **bài học riêng** (tra theo bảng mục 2, dùng đúng `x`,`b` và toán tử của bước đó — không phải của A1, Ak ban đầu). **Bài học của cả phép tính = bài học lớn nhất trong các bước** (vì học sinh cần biết mọi kỹ thuật xuất hiện trong bài mới giải được). Một phép tính nhiều bước tự nhiên "chạm" vào nhiều bài học cùng lúc — đây là cách hữu ích để phủ được nhiều bài học trong ít câu hỏi.

Ràng buộc bắt buộc khi dựng chuỗi (xem thêm mục 4):
- Sau **mỗi bước trừ**: `R_(i-1) ≥ A_i` (không được âm ở bất kỳ bước trung gian nào — bàn tính vật lý không biểu diễn được số âm, dù đề chỉ nêu ràng buộc cho kết quả cuối, việc số dư âm giữa chừng khiến bài toán không giải được bằng bàn tính nên **luôn phải đảm bảo mọi kết quả trung gian ≥ 0**).
- Toàn bộ `A1..Ak` phải **cùng số chữ số** (xem mục 4).
- Chỉ được dùng bước nào có *bài học của bước ≤ N* (ở chế độ N) hoặc *nằm trong [A,B]* (ở chế độ khoảng).

---

## 4. Ràng buộc bổ sung của đề bài (áp lên trên bộ quy tắc gốc)

| # | Ràng buộc | Diễn giải khi sinh đề |
|---|---|---|
| 1 | Đề gồm đúng **20 phép tính** | Đếm và đánh số 1-20 |
| 2 | Phủ đúng phạm vi bài học yêu cầu | Chế độ N: các kỹ thuật xuất hiện trong đề phải trải đều từ bài 1 đến bài N (mỗi bài học trong khoảng lý tưởng nên có ít nhất 1 bước tính minh hoạ trong toàn đề). Chế độ A-B: trải đều từ bài A đến bài B, **không** cố tình lặp lại các bài < A. |
| 3 | Kết quả mỗi phép tính: `0 < R_final < 1000` | Kiểm tra sau khi tính toàn bộ chuỗi. Ràng buộc này áp cho **kết quả cuối cùng** của mỗi phép tính (đã cộng/trừ hết các toán hạng) |
| 4 | Đủ cả 2 toán tử `+` và `−` | Xem cách áp dụng ở mục 4.1 ngay dưới — **ưu tiên tuân theo trình tự chương trình học**, không được vi phạm mục 6.1 của tài liệu gốc chỉ để "cho đủ toán tử" |
| 5 | Tối đa 5 toán hạng, mỗi toán hạng tối đa 3 chữ số | Số toán hạng mỗi phép tính: 2-5 (nên trộn nhiều mức để đề đỡ đơn điệu). Mỗi toán hạng: 1-3 chữ số |
| 6 | Các toán hạng trong **cùng một phép tính** phải cùng số chữ số | Ví dụ phép tính có 4 toán hạng thì cả 4 đều là số 2 chữ số, không được trộn 1 và 2 chữ số trong cùng 1 câu. Số chữ số **có thể khác nhau giữa các câu** trong đề (câu 1 dùng số 2 chữ số, câu 2 dùng số 3 chữ số...) |

### 4.1. Cách xử lý ràng buộc "đủ cả 2 toán tử" khi N < 10

Chương trình học chỉ dạy phép trừ từ bài 10 trở đi (mục 6 tài liệu gốc). Do đó:

- **Nếu N ≥ 10** (hoặc khoảng A-B có phần giao với [10,26]): đề **bắt buộc** có cả câu dùng phép cộng và câu dùng phép trừ (và khuyến khích một số phép tính nhiều toán hạng trộn cả `+` lẫn `−` trong cùng một câu để luyện chuyển đổi kỹ thuật).
- **Nếu N < 10** (học sinh chưa học phép trừ) hoặc khoảng A-B hoàn toàn nằm trong [1,9]: **không** được đưa phép trừ vào đề dù ràng buộc "đủ 2 toán tử" có nêu ra, vì điều đó vi phạm nguyên tắc cốt lõi "chỉ ra đề dạng đã học" (mục 6.1 tài liệu gốc — ưu tiên cao hơn). Trong trường hợp này, hãy **báo lại rõ ràng cho người dùng** rằng đề chỉ có phép cộng vì phép trừ chưa được học tới, thay vì âm thầm phá luật hoặc âm thầm bỏ qua yêu cầu.

---

## 5. Quy trình ra đề từng bước (giáo viên suy luận)

### Bước 1 — Xác định phạm vi bài học được phép dùng
Từ đầu vào (N hoặc A-B), tra bảng mục 2 để liệt kê **danh sách các dòng (bài học) được mở**: với chế độ N là {1,...,N}, với chế độ A-B là {A,...,B}. Ghi chú riêng bài nào là Mix (19-26) vì nó phụ thuộc bài gốc tương ứng (Mix của Cộng 6-9 chỉ mở khi ≥19, Mix của Trừ 6-9 chỉ mở khi ≥23).

### Bước 2 — Lập kế hoạch phủ bài học cho 20 câu
- Nếu số bài học cần phủ **L ≤ 20**: dự kiến mỗi bài học xuất hiện tối thiểu 1 lần (làm tròn phân bổ, các bài học *mới nhất* — tức gần N hoặc gần B nhất — nên được lặp lại nhiều hơn 1 lần vì đó là kỹ thuật học sinh cần luyện nhiều nhất; các bài học cũ hơn chỉ cần xuất hiện ôn lại 1 lần, có thể lồng ghép qua các bước phụ trong phép tính nhiều toán hạng).
- Nếu **L > 20** (ví dụ chế độ N=26, ôn toàn chương trình): không thể mỗi bài học một câu riêng. Ưu tiên dùng nhiều **phép tính nhiều toán hạng (4-5 toán hạng)** để mỗi câu chạm được 3-4 bài học khác nhau qua các bước, giúp tổng số bài học được phủ trong 20 câu vẫn trải rộng hết {1..L}.
- Lập một bảng nháp (không cần đưa vào đề cuối) liệt kê: câu số → các bài học dự kiến chạm tới, để tự kiểm tra độ phủ trước khi sinh số cụ thể.

### Bước 3 — Với mỗi câu, sinh cụ thể
1. Chọn **số toán hạng k** (2-5, nên đa dạng qua các câu — ví dụ 6-8 câu 2 toán hạng, 6-8 câu 3 toán hạng, còn lại 4-5 toán hạng).
2. Chọn **số chữ số d** cho toàn bộ toán hạng của câu này (1, 2, hoặc 3 — không nhất thiết cố định qua cả đề, nhưng cố định trong 1 câu).
3. Với từng bước trong chuỗi (theo mục 3), chọn bài học mục tiêu theo kế hoạch ở Bước 2, tra bảng mục 2 lấy `b` và tập `x` hợp lệ, chọn 1 giá trị `x` cụ thể.
4. Sinh số `A` (toán hạng trước bước đó) có đúng `d` chữ số, chữ số hàng đơn vị = `x`, chữ số đầu khác 0, các chữ số còn lại tuỳ ý (0-9). Với trừ, đảm bảo `A ≥ 10` khi kỹ thuật là BL/Mix (tự động đúng nếu `d ≥ 2`).
5. Sinh `B` (toán hạng cộng/trừ vào) có đúng `d` chữ số, chữ số hàng đơn vị = `b`, chữ số đầu khác 0. Nếu là phép trừ, đảm bảo `A ≥ B` (so toàn bộ số, không chỉ hàng đơn vị).
6. Tính `R = A op B`. Nếu là bước không phải bước cuối, đây trở thành `A` của bước kế tiếp, tiếp tục bước 3.3-3.5 cho toán hạng tiếp theo.
7. Sau bước cuối, kiểm tra `0 < R_final < 1000`. Nếu vi phạm, chỉnh lại các chữ số ở hàng chục/trăm (không đổi hàng đơn vị `x`,`b` — vì đổi sẽ đổi luôn kỹ thuật) và tính lại; nếu không chỉnh được, giảm số chữ số `d` hoặc giảm số toán hạng `k` và làm lại từ bước 3.1 cho câu đó.

### Bước 4 — Đối chiếu ngược để xác nhận kỹ thuật
Với mỗi bước đã sinh, dùng công thức tổng quát ở mục 4.2 (cộng) / 5.2 (trừ) của `references/bsmart-rule.md` để tính lại kỹ thuật từ `(x,b)` vừa dùng, đối chiếu đúng với kỹ thuật/bài học dự định ở Bước 3.3. Nếu công thức và bảng tra (mục 2 ở đây) ra kết quả khác nhau, **ưu tiên bảng tra chính thức** (mục 4.1/5.1 tài liệu gốc), vì đó là nguồn chuẩn.

### Bước 5 — Kiểm tra tổng thể toàn đề (checklist bắt buộc trước khi giao đề)

- [ ] Đúng 20 câu, đánh số 1-20
- [ ] Mỗi câu: `0 < kết quả cuối < 1000`
- [ ] Mỗi câu: 2-5 toán hạng, mỗi toán hạng 1-3 chữ số
- [ ] Trong từng câu: tất cả toán hạng cùng số chữ số
- [ ] Mọi bước trung gian (phép trừ) không âm
- [ ] Có cả câu `+` và câu `−` (trừ khi N < 10, xem mục 4.1 — khi đó ghi chú rõ cho người dùng)
- [ ] Mọi bài học chạm tới trong đề đều ≤ N (chế độ N) hoặc nằm trong [A,B] (chế độ khoảng) — không có kỹ thuật "học lố"
- [ ] Toàn bộ các bài học trong phạm vi yêu cầu (1..N hoặc A..B) đều được đại diện ít nhất một lần trong đề (nếu L ≤ 20); nếu L > 20 thì các bài học được trải đều hợp lý qua các bước của phép tính nhiều toán hạng
- [ ] Không có câu nào bị lặp y hệt số liệu

Nếu bất kỳ mục nào không đạt, quay lại Bước 3 sửa câu tương ứng — không giao đề khi chưa qua hết checklist.

---

## 6. Định dạng đầu ra

Trình bày đề dưới dạng danh sách 20 câu đánh số, chỉ hiện phép tính (không hiện đáp án, không hiện bài học/kỹ thuật — đó là thông tin nội bộ của giáo viên khi ra đề), ví dụ:

```
1) 234 + 456 = ?
2) 87 − 39 = ?
3) 12 + 34 − 21 = ?
...
20) 456 + 231 − 178 + 89 = ?
```

Sau đề, có thể chủ động hỏi người dùng có muốn kèm **đáp án** (danh sách kết quả tương ứng) hoặc **bảng chú thích bài học/kỹ thuật từng câu** (hữu ích nếu người dùng là giáo viên muốn kiểm tra lại độ phủ chương trình) hay không, thay vì mặc định in kèm — giữ đề bài gọn gàng như một tờ bài tập thật.

---

## 7. Ví dụ suy luận mẫu (rút gọn)

Yêu cầu: "Ra đề cho học sinh đang học tới bài 12."

- Bước 1: N=12 → phạm vi mở: Cộng bài 1-9 (toàn bộ kỹ thuật KCT/BN/BL của b=1..9, không có Mix), Trừ bài 10-12 (b=1,2,3, đủ KCT/BN/BL, chưa có Trừ b=4 trở đi, chưa có Mix nào).
- Bước 2: L = 12 bài học ≤ 20 → mỗi bài tối thiểu 1 câu; ưu tiên lặp thêm ở các bài 10-12 (mới học) và một vài câu ôn cộng bài 1-9.
- Bước 3 (câu ví dụ, mục tiêu bài 12 — Trừ, b=3, kỹ thuật Anh bạn lớn): tra bảng 2.2 dòng bài 12, cột BL: `x ∈ {0,1,2}`. Chọn d=2 chữ số, x=1 → A có thể là 41 (A≥10 ✓). b=3 → B=13. Kiểm tra A≥B: 41≥13 ✓. R=41−13=28, thoả 0<28<1000. Đối chiếu công thức 5.2: x=1<b=3 (nhánh mượn chục), x<5 và x+(10-3)=1+7=8 không <5 → không rơi Mix theo công thức nhưng bảng chính thức ghi BL cho x=1,b=3 → dùng bảng, xác nhận BL, đúng bài 12. ✓
- Lặp quy trình cho 19 câu còn lại theo kế hoạch phủ ở Bước 2, rồi chạy checklist Bước 5.

---

## 8. Tệp tham chiếu

- `references/bsmart-rule.md` — bộ quy tắc gốc đầy đủ (định nghĩa 4 kỹ thuật, ví dụ minh hoạ thao tác hạt bàn tính, công thức lập trình hoá chi tiết, bảng bổ túc 5/10). Mở file này khi cần: giải thích cách giải một phép tính cho học sinh, kiểm chứng sâu hơn công thức 4.2/5.2, hoặc khi có nghi vấn về một dòng trong bảng mục 2 ở trên.
