
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Esegui un fit su istogrammi di dati o MC.")
    parser.add_argument('--inizio', required=True, type=float)
    parser.add_argument('--fine', required=True, type=float)
    parser.add_argument('--passo', required=True, type=float)

    args = parser.parse_args()

    if args.passo == 0:
        raise ValueError("Il args.passo non può essere zero.")

    lista = []
    valore = args.inizio
    if args.passo > 0:
        while valore <= args.fine:
            lista.append(valore)
            valore += args.passo
    else:  # args.passo negativo
        while valore >= args.fine:
            lista.append(valore)
            valore += args.passo
    list_arrotondata = [round(num, 6) for num in lista]
    print(list_arrotondata)
    # return lista
