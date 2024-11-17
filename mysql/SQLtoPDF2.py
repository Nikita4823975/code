import mysql.connector
from fpdf import FPDF
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import messagebox, simpledialog, Toplevel
import os
import threading
from queue import Queue


# Функция подключения к базе данных
def connect_to_db(user, password, host, database):
    try:
        cnx = mysql.connector.connect(
            user=user,
            password=password,
            host=host,
            database=database,
            use_unicode=True,
            charset="utf8"
        )
        return cnx
    except mysql.connector.Error as err:
        messagebox.showerror("Ошибка", f"Ошибка подключения к базе данных: {err}")
        return None


# Функция генерации статистики по серверам
def generate_server_statistics(cnx, order_by, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
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
                employees e ON s.Technician_ID = e.ID_Employee
            ORDER BY s.ID_Server {order_by};
        """
        cursor.execute(query)
        data = cursor.fetchall()
        cursor.close()  # Закрываем курсор после использования
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
        os.startfile("server_statistics.pdf")
    except Exception as e:
        error_queue.put(e)


# Функция генерации договора аренды
# Функция генерации договора аренды
def generate_rental_contract(cnx, contract_id, error_queue):
    try:
        cursor = cnx.cursor()

        # Получение данных из базы данных
        query = f"""
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
                employees e ON c.Seller_ID = e.ID_Employee
            WHERE c.ID_Contracts = {contract_id};
        """
        cursor.execute(query)
        data = cursor.fetchone()
        cursor.close()  # Закрываем курсор после использования

        if data is None:
            error_queue.put("No contract data found.")
            return

        # Определение типа арендатора и соответствующего шаблона
        if data[8] == 'Individual':
            template_file = 'contract_template_individual.txt'
            renter_surname = data[1]
            renter_name = data[2]
            renter_legal_name = ""
        elif data[8] == 'Legal':
            template_file = 'contract_template_legal.txt'
            renter_surname = ""
            renter_name = ""
            renter_legal_name = data[3]

        # Чтение шаблона договора из файла
        with open(template_file, 'r', encoding='utf-8') as file:
            contract_template = file.read()

        # Подставляем данные в шаблон
        monthly_payment = data[5]
        start_date = data[6]
        end_date = data[7]  # Добавлено поле end_date
        seller_surname = data[12]
        seller_name = data[11]  # Исправлено индекс для имени продавца
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
        pdf.set_font("DejaVuSans", size=10)  # Уменьшаем размер шрифта

        for line in encoded_text.split('\n'):
            pdf.multi_cell(0, 5,
                           txt=line)  # Используем multi_cell для автоматического разбиения текста на несколько строк и страниц

        pdf.output("rental_contract.pdf")
        os.startfile("rental_contract.pdf")
    except Exception as e:
        error_queue.put(e)


# Функция генерации прибыли по месяцам с гистограммой (главный поток)
def generate_profit_by_month_main(cnx, start_date, end_date, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
            SELECT 
                YEAR(p.PaymentDate) AS Year,
                MONTH(p.PaymentDate) AS Month,
                SUM(p.PaymentAmount) AS TotalPayment
            FROM 
                payments p
            WHERE p.PaymentDate BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 
                YEAR(p.PaymentDate), MONTH(p.PaymentDate)
            ORDER BY 
                Year, Month;
        """
        cursor.execute(query)
        data = cursor.fetchall()
        cursor.close()  # Закрываем курсор после использования

        if not data:  # Проверяем, есть ли данные
            error_queue.put("No payment data found.")
            return

        # Данные для графика
        months = [f"{row[0]}-{row[1]:02d}" for row in data]
        payments = [row[2] for row in data]

        # Создание графика в главном потоке
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
        os.startfile("profit_by_month.pdf")
    except Exception as e:
        error_queue.put(e)


def login_window():
    def login():
        user = user_entry.get()
        password = password_entry.get()
        host = host_entry.get()
        database = database_entry.get()

        cnx = connect_to_db(user, password, host, database)

        if cnx is not None:
            login_window.destroy()
            document_window(cnx)

    global login_window
    login_window = tk.Tk()
    login_window.title("Авторизация")

    tk.Label(login_window, text="Пользователь").grid(row=0)
    tk.Label(login_window, text="Пароль").grid(row=1)
    tk.Label(login_window, text="Хост").grid(row=2)
    tk.Label(login_window, text="База данных").grid(row=3)

    global user_entry
    user_entry = tk.Entry(login_window)
    user_entry.grid(row=0, column=1)

    global password_entry
    password_entry = tk.Entry(login_window, show="*")
    password_entry.grid(row=1, column=1)

    global host_entry
    host_entry = tk.Entry(login_window)
    host_entry.grid(row=2, column=1)

    global database_entry
    database_entry = tk.Entry(login_window)
    database_entry.grid(row=3, column=1)

    tk.Button(login_window, text="Подтвердить", command=login).grid(row=4, column=0, columnspan=2)


def document_window(cnx):
    error_queue = Queue()

    def generate_server_stats():
        def get_order_by():
            order_by_window = Toplevel(document_window)
            order_by_window.title("Выбор порядка сортировки")

            tk.Label(order_by_window, text="Выберите порядок сортировки:").pack()
            tk.Button(order_by_window, text="По возрастанию", command=lambda: [order_by_window.destroy(),
                                                                               threading.Thread(
                                                                                   target=generate_server_statistics,
                                                                                   args=(cnx, 'ASC',
                                                                                         error_queue)).start()]).pack()
            tk.Button(order_by_window, text="По убыванию", command=lambda: [order_by_window.destroy(), threading.Thread(
                target=generate_server_statistics, args=(cnx, 'DESC', error_queue)).start()]).pack()

        get_order_by()

    def generate_rental_contract_doc():
        def get_contract_id():
            contract_id = simpledialog.askinteger("Введите ID договора аренды", "ID договора аренды")
            if contract_id is not None:
                threading.Thread(target=generate_rental_contract, args=(cnx, contract_id, error_queue)).start()

        get_contract_id()

    def generate_profit_by_month_doc():
        def get_dates():
            while True:
                start_date = simpledialog.askstring("Введите начальную дату", "Начальная дата (YYYY-MM-DD)")
                end_date = simpledialog.askstring("Введите конечную дату", "Конечная дата (YYYY-MM-DD)")

                # Проверка формата дат
                try:
                    from datetime import datetime
                    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

                    # Проверка того, что начальная дата не позднее конечной
                    if start_date_obj > end_date_obj:
                        messagebox.showerror("Ошибка", "Начальная дата должна быть раньше конечной.")
                        continue

                    generate_profit_by_month_main(cnx, start_date, end_date, error_queue)
                    break
                except ValueError:
                    messagebox.showerror("Ошибка", "Неправильный формат даты. Используйте YYYY-MM-DD.")

        get_dates()

    # Функция генерации прибыли по месяцам с гистограммой (главный поток)
    def generate_profit_by_month_main(cnx, start_date, end_date, error_queue):
        try:
            cursor = cnx.cursor()
            query = f"""
                SELECT 
                    YEAR(p.PaymentDate) AS Year,
                    MONTH(p.PaymentDate) AS Month,
                    SUM(p.PaymentAmount) AS TotalPayment
                FROM 
                    payments p
                WHERE p.PaymentDate BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY 
                    YEAR(p.PaymentDate), MONTH(p.PaymentDate)
                ORDER BY 
                    Year, Month;
            """
            cursor.execute(query)
            data = cursor.fetchall()
            cursor.close()  # Закрываем курсор после использования

            if not data:  # Проверяем, есть ли данные
                error_queue.put("No payment data found.")
                return

            # Данные для графика
            months = [f"{row[0]}-{row[1]:02d}" for row in data]
            payments = [row[2] for row in data]

            # Создание графика в главном потоке
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
            os.startfile("profit_by_month.pdf")
        except Exception as e:
            error_queue.put(e)

    def check_errors():
        if not error_queue.empty():
            error = error_queue.get()
            messagebox.showerror("Ошибка", f"Ошибка при генерации документа: {error}")
        document_window.after(100, check_errors)

    global document_window
    document_window = tk.Tk()
    document_window.title("Документы")

    tk.Button(document_window, text="Статистика по серверам", command=generate_server_stats).pack(pady=10)
    tk.Button(document_window, text="Договор аренды", command=generate_rental_contract_doc).pack(pady=10)
    tk.Button(document_window, text="Прибыль по месяцам", command=generate_profit_by_month_doc).pack(pady=10)

    check_errors()


if __name__ == "__main__":
    login_window()
    tk.mainloop()