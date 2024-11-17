import mysql.connector
from fpdf import FPDF
import matplotlib.pyplot as plt

# Функция подключения к базе данных
def connect_to_db():
    cnx = mysql.connector.connect(
        user='root',
        password='1234',
        host='localhost',
        database='kurs',
        use_unicode=True,
        charset="utf8"
    )
    return cnx

# Функция выбора типа документа
def choose_document_type():
    print("Выберите тип документа:")
    print("1. Статистика по серверам")
    print("2. Договор аренды")
    print("3. Прибыль по месяцам")
    choice = input("Введите номер выбора: ")
    return choice

# Функция генерации статистики по серверам
def generate_server_statistics(cnx):
    cursor = cnx.cursor()
    query = """
        SELECT 
            s.ID_Server,
            s.Adress,
            s.City,
            m.ModelName AS ServerModel,
            s.StorageLeft,
            s.MonthlyRentCost,
            e.Surname AS TechnicianSurname,
            e.Name AS TechnicianName
        FROM 
            servers s
        JOIN 
            models m ON s.Model_ID = m.ID_Model
        JOIN 
            employees e ON s.Technician_ID = e.ID_Employee;
    """
    cursor.execute(query)
    data = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
    pdf.set_font("DejaVuSans", size=12)
    pdf.cell(200, 10, txt="Статистика по серверам", ln=True, align='C')

    pdf.set_font("DejaVuSans", size=12)
    for col in columns:
        pdf.cell(40, 10, txt=col, border=1, align='C')
    pdf.ln(10)

    for row in data:
        for cell in row:
            pdf.cell(40, 10, txt=str(cell), border=1, align='C')
        pdf.ln(10)

    pdf.output("server_statistics.pdf")


# Функция генерации договора аренды
def generate_rental_contract(cnx):
    cursor = cnx.cursor()

    # Получение данных из базы данных
    query = """
        SELECT 
            c.ID_Contracts,
            ri.Surname AS RenterSurname,
            ri.Name AS RenterName,
            rl.Name AS RenterLegalName,
            c.RentedSpace,
            c.MonthlyPayments,
            c.StartDate,
            c.EndDate,
            c.RenterType,
            s.Adress AS ServerAdress,
            s.City AS ServerCity,
            e.Surname AS SellerSurname,
            e.Name AS SellerName,
            e.AccountNumber AS SellerAccountNumber
        FROM 
            contracts c
        LEFT JOIN 
            renterindividual ri ON c.Renter_ID = ri.ID_RenterIndividual AND c.RenterType = 'Individual'
        LEFT JOIN 
            renterlegal rl ON c.Renter_ID = rl.ID_RenterLegal AND c.RenterType = 'Legal'
        JOIN 
            servers s ON c.Server_ID = s.ID_Server
        JOIN 
            employees e ON c.Seller_ID = e.ID_Employee;
    """
    cursor.execute(query)
    data = cursor.fetchone()

    if data is None:
        print("No contract data found.")
        return

    # Чтение шаблона договора из файла
    with open('contract_template_individual.txt', 'r', encoding='utf-8') as file:
        contract_template = file.read()

    # Подставляем данные в шаблон
    renter_surname = data[1]
    renter_name = data[2]
    renter_legal_name = data[3]
    monthly_payment = data[5]
    start_date = data[6]
    end_date = data[7] # Добавлено поле end_date
    seller_surname = data[12]
    seller_name = data[11] # Исправлено индекс для имени продавца
    email = "nikita.buharinov@mail.ru"

    filled_contract = contract_template.format(
        renter_surname=renter_surname,
        renter_name=renter_name,
        renter_legal_name=renter_legal_name,
        monthly_payment=monthly_payment,
        start_date=start_date,
        end_date=end_date,
        seller_surname=seller_surname,
        seller_name=seller_name,
        email=email
    )

    # Кодировка текста перед записью в PDF
    encoded_text = filled_contract.encode('utf-8', errors='ignore').decode('utf-8')

    # Создание PDF-документа
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
    pdf.set_font("DejaVuSans", size=10) # Уменьшаем размер шрифта

    for line in encoded_text.split('\n'):
        pdf.multi_cell(0, 5, txt=line) # Используем multi_cell для автоматического разбиения текста на несколько строк и страниц

    pdf.output("rental_contract.pdf")


# Функция генерации прибыли по месяцам с гистограммой
def generate_profit_by_month(cnx):
    cursor = cnx.cursor()
    query = """
        SELECT 
            YEAR(p.PaymentDate) AS Year,
            MONTH(p.PaymentDate) AS Month,
            SUM(p.PaymentAmount) AS TotalPayment
        FROM 
            payments p
        GROUP BY 
            YEAR(p.PaymentDate), MONTH(p.PaymentDate)
        ORDER BY 
            Year, Month;
    """
    cursor.execute(query)
    data = cursor.fetchall()

    # Данные для графика
    months = [f"{row[0]}-{row[1]:02d}" for row in data]
    payments = [row[2] for row in data]

    # Создание графика
    plt.figure(figsize=(10, 5))
    plt.bar(months, payments)
    plt.xlabel('Месяц')
    plt.ylabel('Общая сумма платежей')
    plt.title('Прибыль по месяцам')
    plt.xticks(rotation=90)  # Поворот меток месяцев для лучшей читаемости
    plt.tight_layout()

    # Сохранение графика как файл
    plt.savefig('profit_by_month_graph.png', dpi=300)

    # Создание PDF-документа
    pdf = FPDF()

    # Добавление первой страницы для графика
    pdf.add_page()

    # Включение графика в PDF-документ
    pdf.image('profit_by_month_graph.png', x=10, y=50, w=190)

    # Добавление второй страницы для таблицы
    pdf.add_page()

    # Заголовок таблицы
    pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
    pdf.set_font("DejaVuSans", size=12)

    # Заголовки таблицы
    pdf.cell(40, 10, txt="Год-Месяц", border=1, align='C')
    pdf.cell(60, 10, txt="Общая сумма платежей", border=1, align='C')

    # Переход на новую строку после заголовков
    pdf.ln(10)

    # Данные таблицы
    for i in range(len(data)):
        pdf.cell(40, 10, txt=f"{data[i][0]}-{data[i][1]:02d}", border=1, align='C')
        pdf.cell(60, 10, txt=str(data[i][2]), border=1, align='C')

        # Переход на новую строку после каждой строки данных
        pdf.ln(10)

    pdf.output("profit_by_month.pdf")


def main():
    cnx = connect_to_db()

    choice = choose_document_type()

    if choice == "1":
        generate_server_statistics(cnx)
    elif choice == "2":
        generate_rental_contract(cnx)
    elif choice == "3":
        generate_profit_by_month(cnx)
    else:
        print("Неправильный выбор.")

    cnx.close()


if __name__ == "__main__":
    main()

